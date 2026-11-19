/*
  FIX: Duration 60 -> 61 la salvarea unei oferte FARA valoare reziduala (RV = 0)

  Cauza:
    uspWeb_AfterSaveQuoteProduct_{95C4750E-...} (pasul "forward") scade (NIA + PS) * Periodicity
    din termen DOAR cand ISNULL(ResidualValueAmount,0) <> 0:
        update #ResidualParameters
           set TermCH = TermUDF - (isnull(@NoInstAdv,0) + PS) * Periodicity
         where ISNULL(ResidualValueAmount,0) <> 0
    In schimb, procedura de mai jos (pasul "reverse", rulat dupa generarea scadentarului)
    aduna (NIA + PS) * Periodicity NECONDITIONAT:
        set @rv_TermUDF = @rv_Cterm + (@rv_NIA + @rv_PS) * @rv_Per
    => cu RV:    60 -> 59 (Cterm) -> 59 rate -> 59 + 1 = 60  (corect)
    => fara RV:  60 -> 60 (Cterm) -> 60 rate -> 60 + 1 = 61  (BUG)

  Rezolvare:
    Se oglindeste conditia din forward: (NIA + PS) se aduna inapoi DOAR daca exista RV.
    Liniile modificate sunt marcate cu  -- >>> FIX

  NOTA: corpul procedurii este reconstruit din trace-ul SQL Profiler (apar doar
  instructiunile executate). Aplicati modificarile marcate cu ">>> FIX" peste
  sursa reala a procedurii din repository, nu inlocuiti orbeste intreaga procedura.
*/

ALTER PROCEDURE [dbo].[uspWeb_AfterSaveQuoteProductSchedule_{95C4750E-3025-4B8E-95D2-646F372A7863}]
    @QuoteProductId INT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @dateS DATETIME, @dateE DATETIME, @months INT, @RealTerm INT;
    DECLARE @VCP_UseRVPO INT, @VCP_DLIT_RVPO INT, @VCP_DLIT_CTERM INT;

    IF EXISTS (
          SELECT 1
          FROM vwWebQuoteProduct
          WHERE QuoteProductId = @QuoteProductId
            AND ISNULL(ScheduleIsConfigurable, 0) = 1
          )
    BEGIN
        SELECT TOP 1 @dateS = ls.DueDate
            FROM WebLeasingSchedule ls(NOLOCK)
            WHERE ls.QuoteProductId = @QuoteProductId
              AND ls.AmountTypeId = 4
            ORDER BY ls.MonthNo;

        SELECT TOP 1 @dateE = ls.DueDate
            FROM WebLeasingSchedule ls(NOLOCK)
            WHERE ls.QuoteProductId = @QuoteProductId
              AND ls.AmountTypeId = 4
            ORDER BY ls.MonthNo DESC;

        SELECT @months = DATEDIFF(MONTH, @dateS, @dateE) + 1;

        UPDATE WebQuoteProduct
            SET MonthlyPaymentAmount = NULL --, Duration = CASE WHEN ISNULL(@months,Duration) < MinDuration THEN Duration ELSE ISNULL(@months,Duration) END
            WHERE QuoteProductId = @QuoteProductId;
    END

    select @VCP_UseRVPO = PropertyId
        from Property(nolock)
        where PropertyCode = N'VCP_UseRVPO';

    select @VCP_DLIT_RVPO = PropertyId
        from Property(nolock)
        where PropertyCode = N'VCP_DLIT_RVPO';

    select @VCP_DLIT_CTERM = PropertyId
        from Property(nolock)
        where PropertyCode = N'VCP_DLIT_CTERM';

    declare @rv_IsRVPO bit = 0, @rv_NIA int = 0, @rv_PS int = 0, @rv_Per int = 1,
            @rv_AddMonths int = 0, @rv_Rows int = 0, @rv_Cterm int, @rv_TermUDF int,
            -- FIX interest reset (vezi mai jos)
            @rv_IsFixed bit = 0, @rv_SchInterestCnt int = 0, @rv_SchInterest decimal(18, 6),
            -- >>> FIX: flag "exista valoare reziduala" (aceeasi conditie ca in uspWeb_AfterSaveQuoteProduct_)
            @rv_HasRV bit = 0;                                                             -- >>> FIX

    select @rv_IsRVPO = 1,
           @rv_Per = isnull(wqp.Periodicity, 1),
           @rv_PS  = case when lower(st.ScheduleTypeName) like N'%advance%' then 1 else 0 end,
           @rv_HasRV = case when isnull(wqp.ResidualValueAmount, 0) <> 0 then 1 else 0 end   -- >>> FIX
    from WebQuoteProduct wqp (nolock)
    join ScheduleType st (nolock) on st.ScheduleTypeId = wqp.ScheduleTypeId
    join LeasingFinancialProductProperty lfpp (nolock)
         on lfpp.ProductId = wqp.ProductId and lfpp.PropertyId = @VCP_UseRVPO and lfpp.PropertyValue = N'Yes'
    where wqp.QuoteProductId = @QuoteProductId;

    if @rv_IsRVPO = 1
    begin
        select @rv_NIA = isnull(lxp.PropertyValue, 0)
            from WebQuoteProduct wqp (nolock)
            join LeasingFinancialProductProperty lxp (nolock) on lxp.ProductId = wqp.ProductId
            join Property p (nolock) on p.PropertyId = lxp.PropertyId and p.PropertyCode = N'VCP_L_NIA'
            where wqp.QuoteProductId = @QuoteProductId;

        select top 1 @rv_AddMonths = isnull(AdditionalMonthNo, 0)
            from DocStruct_WebCellParamHeader (nolock)
            where QuoteProductId = @QuoteProductId;

        select @rv_Rows = count(*)
            from WebLeasingSchedule (nolock)
            where QuoteProductId = @QuoteProductId and AmountTypeId = 4;

        if @rv_Rows > 0
        begin
            set @rv_Cterm   = @rv_Rows * @rv_Per - @rv_AddMonths;

            -- >>> FIX: in forward (uspWeb_AfterSaveQuoteProduct_) termenul contabil se scurteaza cu
            -- >>> FIX: (NIA + PS) * Per DOAR cand exista RV; aici il adunam inapoi DOAR in acelasi caz,
            -- >>> FIX: altfel Duration = Cterm (fara RV rezulta 60, nu 61).
            set @rv_TermUDF = @rv_Cterm
                            + case when @rv_HasRV = 1 then (@rv_NIA + @rv_PS) * @rv_Per else 0 end;   -- >>> FIX

            update WebQuoteProduct
               set Duration = @rv_TermUDF
             where QuoteProductId = @QuoteProductId and Duration <> @rv_TermUDF;

            update WebQuoteProductProperty
               set PropertyValue = cast(@rv_Cterm as varchar(255))
             where QuoteProductId = @QuoteProductId and PropertyId = @VCP_DLIT_CTERM
               and PropertyValue <> cast(@rv_Cterm as varchar(255));

            update sd set Duration = @rv_Cterm
              from WebLeasingServiceDetail sd
              join WebQuoteProduct wqp (nolock) on wqp.QuoteProductId = sd.QuoteProductId
              join LeasingFinancialProductXServiceType x (nolock)
                   on x.ProductId = wqp.ProductId and x.ServiceTypeId = sd.ServiceTypeId
             where sd.QuoteProductId = @QuoteProductId;
        end

        -- FIX interest reset
        select @rv_IsFixed = isnull(lit.IsFixed, 0)
            from WebQuoteProduct wqp (nolock)
            join LeasingFinancialProduct lfp (nolock) on lfp.ProductId = wqp.ProductId
            join LeasingInterestType lit (nolock) on lit.InterestTypeId = lfp.InterestTypeId
            where wqp.QuoteProductId = @QuoteProductId;

        select @rv_SchInterestCnt = count(distinct ls.InterestPercent),
               @rv_SchInterest    = min(ls.InterestPercent)
            from WebLeasingSchedule ls (nolock)
            where ls.QuoteProductId = @QuoteProductId
              and ls.AmountTypeId = 4
              and ls.InterestPercent is not null;

        if @rv_IsFixed = 1 and @rv_SchInterestCnt = 1 and @rv_SchInterest is not null
            update WebQuoteProduct
               set InterestPercent = @rv_SchInterest
             where QuoteProductId = @QuoteProductId
               and abs(isnull(InterestPercent, -1) - @rv_SchInterest) > 0.000001;
    end

    select @RealTerm = case
            when lfpp.ProductId is not null
              then cast(wqpp1.PropertyValue as int)
            else lad.Duration
            end
        FROM WebQuoteProduct lad(nolock)
        JOIN LeasingFinancialProduct lfp(nolock)
          on lad.ProductId = lfp.ProductId
        LEFT JOIN LeasingFinancialProductProperty lfpp(nolock)
          on lad.ProductId = lfpp.ProductId
            and lfpp.PropertyId = @VCP_UseRVPO
            and isnull(lfpp.PropertyValue, 'No') = 'Yes'
        LEFT JOIN WebQuoteProductProperty wqpp1 WITH (NOLOCK)
          on wqpp1.QuoteProductId = lad.QuoteProductId
            and wqpp1.PropertyId = @VCP_DLIT_CTERM
        WHERE lad.QuoteProductId = @QuoteProductId;

    update DocStruct_WebCellParamHeader
        set Duration = @RealTerm
        where QuoteProductId = @QuoteProductId;
END
GO

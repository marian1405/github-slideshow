USE [CharismaERP_IT]
GO
/****** Object:  StoredProcedure [dbo].[uspWeb_AfterSaveQuoteProductSchedule_{95C4750E-3025-4B8E-95D2-646F372A7863}]    Script Date: 19.11.2026 11:29:35 ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
ALTER PROCEDURE [dbo].[uspWeb_AfterSaveQuoteProductSchedule_{95C4750E-3025-4B8E-95D2-646F372A7863}] @QuoteProductId INT
AS
BEGIN
  IF exists (
      SELECT 1
      FROM vwWebQuoteProduct
      WHERE QuoteProductId = @QuoteProductId
        AND ISNULL(ScheduleIsConfigurable, 0) = 1
      )
  BEGIN
    DECLARE @dateS DATETIME,
      @dateE DATETIME,
      @months INT

    SELECT TOP 1 @dateS = ls.DueDate
    FROM WebLeasingSchedule ls(NOLOCK)
    WHERE ls.QuoteProductId = @QuoteProductId
      AND ls.AmountTypeId = 4
    ORDER BY ls.MonthNo

    SELECT TOP 1 @dateE = ls.DueDate
    FROM WebLeasingSchedule ls(NOLOCK)
    WHERE ls.QuoteProductId = @QuoteProductId
      AND ls.AmountTypeId = 4
    ORDER BY ls.MonthNo DESC

    SELECT @months = DATEDIFF(MONTH, @dateS, @dateE) + 1

    UPDATE WebQuoteProduct
    SET MonthlyPaymentAmount = NULL --, Duration = CASE WHEN ISNULL(@months,Duration) < MinDuration THEN Duration ELSE ISNULL(@months,Duration) END
    WHERE QuoteProductId = @QuoteProductId;

    declare @VCP_UseRVPO int,
      @VCP_DLIT_RVPO int,
      @VCP_DLIT_CTERM int,
      @RealTerm int,
      @RealVR ChAmount

    select @VCP_UseRVPO = PropertyId
    from Property(nolock)
    where PropertyCode = N'VCP_UseRVPO'

    select @VCP_DLIT_RVPO = PropertyId
    from Property(nolock)
    where PropertyCode = N'VCP_DLIT_RVPO'

    select @VCP_DLIT_CTERM = PropertyId
    from Property(nolock)
    where PropertyCode = N'VCP_DLIT_CTERM'


	--QC59854
	-- RVPO: readucem produsul la termenul comercial, pornind de la scadentarul salvat
    -- VCP scrie Duration = numarul de rate generate; la UseRVPO=Yes ratele sunt Duration-(NIA+PS)*Periodicity,
    -- refacem Duration din scadentar: CTERM = rate salvate, TermUDF = CTERM + (NIA+PS)*Periodicity.
    declare @rv_IsRVPO bit = 0, @rv_NIA int = 0, @rv_PS int = 0, @rv_Per int = 1,
            @rv_AddMonths int = 0, @rv_Rows int = 0, @rv_Cterm int, @rv_TermUDF int,
			-- FIX interest reset (vezi mai jos)
            @rv_IsFixed bit = 0, @rv_SchInterestCnt int = 0, @rv_SchInterest decimal(18, 6),
            @rv_HasRV bit = 0 --QCxxxx

    select @rv_IsRVPO = 1,
           @rv_Per = isnull(wqp.Periodicity, 1),
           @rv_PS  = case when lower(st.ScheduleTypeName) like N'%advance%' then 1 else 0 end,
           @rv_HasRV = case when isnull(wqp.ResidualValueAmount, 0) <> 0 then 1 else 0 end --QCxxxx
    from WebQuoteProduct wqp (nolock)
    join ScheduleType st (nolock) on st.ScheduleTypeId = wqp.ScheduleTypeId
    join LeasingFinancialProductProperty lfpp (nolock)
         on lfpp.ProductId = wqp.ProductId and lfpp.PropertyId = @VCP_UseRVPO and lfpp.PropertyValue = N'Yes'
    where wqp.QuoteProductId = @QuoteProductId

    if @rv_IsRVPO = 1
    begin
        select @rv_NIA = isnull(lxp.PropertyValue, 0)
        from WebQuoteProduct wqp (nolock)
        join LeasingFinancialProductProperty lxp (nolock) on lxp.ProductId = wqp.ProductId
        join Property p (nolock) on p.PropertyId = lxp.PropertyId and p.PropertyCode = N'VCP_L_NIA'
        where wqp.QuoteProductId = @QuoteProductId

        select top 1 @rv_AddMonths = isnull(AdditionalMonthNo, 0)
        from DocStruct_WebCellParamHeader (nolock)
        where QuoteProductId = @QuoteProductId

        select @rv_Rows = count(*)
        from WebLeasingSchedule (nolock)
        where QuoteProductId = @QuoteProductId and AmountTypeId = 4

        if @rv_Rows > 0
        begin
            set @rv_Cterm   = @rv_Rows * @rv_Per - @rv_AddMonths
            --QCxxxx: (NIA+PS) se scade in AfterSaveQuoteProduct doar cu RV<>0, deci se aduna inapoi doar cu RV<>0
            set @rv_TermUDF = @rv_Cterm + case when @rv_HasRV = 1 then (@rv_NIA + @rv_PS) * @rv_Per else 0 end

            update WebQuoteProduct
               set Duration = @rv_TermUDF
             where QuoteProductId = @QuoteProductId and Duration <> @rv_TermUDF

            update WebQuoteProductProperty
               set PropertyValue = cast(@rv_Cterm as varchar(255))
             where QuoteProductId = @QuoteProductId and PropertyId = @VCP_DLIT_CTERM
               and PropertyValue <> cast(@rv_Cterm as varchar(255))

            update sd set Duration = @rv_Cterm
              from WebLeasingServiceDetail sd
              join WebQuoteProduct wqp (nolock) on wqp.QuoteProductId = sd.QuoteProductId
              join LeasingFinancialProductXServiceType x (nolock)
                   on x.ProductId = wqp.ProductId and x.ServiceTypeId = sd.ServiceTypeId
             where sd.QuoteProductId = @QuoteProductId

            -- FIX interest reset dupa recalcul (RVPO)
            -- Dupa calculul scadentarului, VCP vede Duration (TermUDF, ex. 60) <> nr. rate generate (CTERM, ex. 59),
            -- trateaza diferenta ca o schimbare de tenor si rescrie WebQuoteProduct.InterestPercent cu
            -- CustomerInterestPercent din LeasingPriceCardMatrix pentru tenorul CTERM (= InterestMaxPercent / BuyRate),
            -- pierzand dobanda pusa manual. Scadentarul tocmai salvat a fost insa calculat cu dobanda de dinainte
            -- de reset (WebLeasingSchedule.InterestPercent pe ratele AmountTypeId = 4), deci refacem InterestPercent
            -- de acolo, la fel cum refacem Duration mai sus. Rulam inainte de uspWeb_ComputeCommission, ca sa
            -- foloseasca dobanda corecta. Doar pentru dobanda fixa si doar daca toate ratele au aceeasi dobanda.
            select @rv_IsFixed = isnull(lit.IsFixed, 0)
            from WebQuoteProduct wqp (nolock)
            join LeasingFinancialProduct lfp (nolock) on lfp.ProductId = wqp.ProductId
            join LeasingInterestType lit (nolock) on lit.InterestTypeId = lfp.InterestTypeId
            where wqp.QuoteProductId = @QuoteProductId

            select @rv_SchInterestCnt = count(distinct ls.InterestPercent),
                   @rv_SchInterest    = min(ls.InterestPercent)
            from WebLeasingSchedule ls (nolock)
            where ls.QuoteProductId = @QuoteProductId
              and ls.AmountTypeId = 4
              and ls.InterestPercent is not null

            if @rv_IsFixed = 1 and @rv_SchInterestCnt = 1 and @rv_SchInterest is not null
            begin
                update WebQuoteProduct
                   set InterestPercent = @rv_SchInterest
                 where QuoteProductId = @QuoteProductId
                   and abs(isnull(InterestPercent, -1) - @rv_SchInterest) > 0.000001
            end
        end
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
    WHERE lad.QuoteProductId = @QuoteProductId

    update DocStruct_WebCellParamHeader
    set Duration = @RealTerm
    where QuoteProductId = @QuoteProductId

    declare @EndDate datetime

    select @EndDate = max(DueDate)
    from WebLeasingSchedule(nolock)
    where QuoteProductId = @QuoteProductId
      and AmountTypeId = 4

    delete DocStruct_WebCellParam
    where QuoteProductId = @QuoteProductId
      and MonthDate > @EndDate
  END;
  ELSE
  BEGIN
    DECLARE @amount ChAmount;

    SELECT TOP 1 @amount = IIF(ISNULL(q.ShowAmountsWithVAT, 0) = 1, ISNULL(ls.TotalAmountWithVAT, 0), ISNULL(ls.Amount, 0) + ISNULL(ls.InterestAmount, 0))
    FROM WebLeasingSchedule ls(NOLOCK)
    JOIN WebQuote q(NOLOCK)
      ON q.QuoteId = @QuoteProductId
    WHERE ls.QuoteProductId = @QuoteProductId
      AND ISNULL(ls.Amount, 0) > 0
      AND ls.AmountTypeId = 4 -- First Installment
    ORDER BY ls.MonthNo;

    UPDATE WebQuoteProduct
    SET MonthlyPaymentAmount = @amount
    WHERE QuoteProductId = @QuoteProductId;
  END;

  DECLARE @QuoteId INT,
    @OfferId INT,
    @OfferSiteId INT,
    @ProductIsSelected BIT;

  SELECT @QuoteId = WQP.QuoteId,
    @ProductIsSelected = WQP.Selected,
    @OfferSiteId = WQP.SiteId
  FROM WebQuoteProduct AS WQP WITH (NOLOCK)
  JOIN LeasingFinancialProduct LFP(nolock)
    on WQP.ProductId = LFP.ProductId
  JOIN WebQuote AS WQ WITH (NOLOCK)
    ON WQP.QuoteId = WQ.QuoteId
      AND WQP.QuoteProductId = @QuoteProductId;

  EXEC uspWeb_ComputeCommission @QuoteProductId


DECLARE @InterestTypeId int  --QC53992
SELECT @InterestTypeId =  p.InterestTypeId
		FROM LeasingFinancialProduct p (nolock)
	    join WebQuoteProduct wqp (nolock) on p.ProductId=wqp.ProductId
		WHERE wqp.QuoteProductId = @QuoteProductId

IF @InterestTypeId IN(102,103,104,105,106) --The calculation and checks on TEGMax are performed only for financial products that use this type.

 BEGIN

  declare @TEG4 float,@TEGMax4 ChPercent

  EXEC uspImplementare_VCP_DLIT_CalculateContractTTI @QuoteId,
    @OfferSiteId,
    @QuoteProductId,
    @TEG4 OUTPUT,
    @TEGMax4 OUTPUT

  IF @TEGMax4 is null
  BEGIN
    RAISERROR (
        N'TEGMax value is not defined in the dictionary: Leasing- > Configuration-> Variable interst-> Floating interest!',
        16,
        1,
        1
        )

    RETURN
  END

  IF @TEG4 > @TEGMax4
  BEGIN
    RAISERROR (
        N'TEG is higher than TEGMax, you are not allowed to change the business status',
        16,
        1,
        1
        )

    RETURN
  END

  END --QC53992--END

  --set RVDueDate
  declare @SchEndDate datetime

  select @SchEndDate = max(DueDate)
  from WebLeasingSchedule(nolock)
  where QuoteProductId = @QuoteProductId
    and AmountTypeId = 4

  declare @VCP_L_NIA int

  select @VCP_L_NIA = PropertyId
  from Property(nolock)
  where PropertyCode = N'VCP_L_NIA'

  declare @GST_DOC_3 int --QC51587

  select @GST_DOC_3 = PropertyId
  from Property(nolock)
  where PropertyCode = N'GST_DOC_3'

  declare @RvTerm int

  select @RvTerm = case
      when isnull(lfpp.PropertyValue, 0) = 1
        and isnull(lfpp1.PropertyValue, '') = ''
        then lad.Periodicity
      else 0
      end
  FROM WebQuoteProduct lad(nolock)
  JOIN LeasingFinancialProduct lfp(nolock)
    on lad.ProductId = lfp.ProductId
  LEFT JOIN LeasingFinancialProductProperty lfpp(nolock)
    on lad.ProductId = lfpp.ProductId
      and lfpp.PropertyId = @VCP_L_NIA
  LEFT JOIN LeasingFinancialProductProperty lfpp1(nolock)
    on lad.ProductId = lfpp1.ProductId
      and lfpp1.PropertyId = @GST_DOC_3 --QC51587
  WHERE lad.QuoteProductId = @QuoteProductId

  update WebLeasingSchedule
  set DueDate = dateadd(month, @RvTerm, @SchEndDate)
  where QuoteProductId = @QuoteProductId
    and AmountTypeId = 5

  IF @ProductIsSelected = 1
  BEGIN
    DECLARE @customProcedureName NVARCHAR(MAX)

    SELECT @customProcedureName = '[uspWeb_SyncQuoteWithBOOffer_' + Id + ']'
    FROM SystemVersionEx(NOLOCK)

    IF @customProcedureName IS not NULL
      AND exists (
        SELECT 1
        from sysobjects
        where id = object_id(@customProcedureName)
          and OBJECTPROPERTY(id, N'IsProcedure') = 1
        )
    BEGIN
      SET @customProcedureName = @customProcedureName + '@QuoteId'

      EXECUTE sp_executesql @customProcedureName,
        N'@QuoteId INT',
        @QuoteId
    END
    ELSE
      EXEC uspWeb_SyncQuoteWithBOOffer @QuoteId
  END
END

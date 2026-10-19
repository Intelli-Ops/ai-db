-- Report:     Monthly road bike sales in Europe
-- Status:     PASSED - awaiting human review
-- Tested on:  {'start_date': '2025-03-01', 'end_date': '2025-03-31'} and held-out {'start_date': '2025-04-01', 'end_date': '2025-04-30'}
-- Written by: nvidia/nemotron-3-ultra-550b-a55b on 2026-10-18, attempt 1 of 1
-- Parameters: @start_date date, @end_date date
-- Tables:     Production.Product, Production.ProductSubcategory, Sales.SalesOrderDetail, Sales.SalesOrderHeader, Sales.SalesTerritory, Sales.SpecialOfferProduct
WITH FilteredOrders AS (
    SELECT 
        st.Name AS Territory,
        sod.OrderQty,
        sod.LineTotal
    FROM Sales.SalesOrderDetail sod
    JOIN Sales.SalesOrderHeader soh ON sod.SalesOrderID = soh.SalesOrderID
    JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
    JOIN Production.Product p ON sod.ProductID = p.ProductID
    JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
    WHERE soh.OrderDate >= @start_date
      AND soh.OrderDate <= @end_date
      AND st.[Group] = 'Europe'
      AND psc.Name = 'Road Bikes'
)
SELECT 
    Territory,
    SUM(OrderQty) AS Units,
    ROUND(SUM(LineTotal), 2) AS Sales
FROM FilteredOrders
GROUP BY Territory
ORDER BY Sales DESC;

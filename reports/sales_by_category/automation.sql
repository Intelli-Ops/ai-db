-- Report:     Monthly sales by product category
-- Status:     PASSED - awaiting human review
-- Tested on:  {'start_date': '2025-03-01', 'end_date': '2025-03-31'} and held-out {'start_date': '2025-04-01', 'end_date': '2025-04-30'}
-- Written by: nvidia/nemotron-3-ultra-550b-a55b on 2026-10-16, attempt 1 of 2
-- Parameters: @start_date date, @end_date date
-- Tables:     Production.Product, Production.ProductCategory, Production.ProductSubcategory, Sales.SalesOrderDetail, Sales.SalesOrderHeader, Sales.SpecialOfferProduct
WITH FilteredOrders AS (
    SELECT SalesOrderID
    FROM Sales.SalesOrderHeader
    WHERE OrderDate >= @start_date
      AND OrderDate < DATEADD(day, 1, @end_date)
)
SELECT 
    pc.Name AS Category,
    SUM(sod.OrderQty) AS Units,
    ROUND(SUM(sod.LineTotal), 2) AS Sales
FROM Sales.SalesOrderDetail sod
JOIN FilteredOrders fo ON sod.SalesOrderID = fo.SalesOrderID
JOIN Production.Product p ON sod.ProductID = p.ProductID
JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
GROUP BY pc.Name
ORDER BY pc.Name;

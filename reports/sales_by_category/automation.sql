-- Report:     Monthly sales by product category
-- Status:     PASSED - awaiting human review
-- Tested on:  {'start_date': '2025-03-01', 'end_date': '2025-03-31'} and held-out {'start_date': '2025-04-01', 'end_date': '2025-04-30'}
-- Written by: gemini-3.5-flash on 2026-10-06, attempt 1 of 5
-- Parameters: @start_date date, @end_date date
-- Tables:     Production.Product, Production.ProductCategory, Production.ProductSubcategory, Sales.SalesOrderDetail, Sales.SalesOrderHeader, Sales.SpecialOfferProduct
SELECT pc.Name AS [Category], SUM(sod.OrderQty) AS [Units], CAST(SUM(sod.LineTotal) AS DECIMAL(18,2)) AS [Sales] FROM Sales.SalesOrderHeader AS soh INNER JOIN Sales.SalesOrderDetail AS sod ON soh.SalesOrderID = sod.SalesOrderID INNER JOIN Production.Product AS p ON sod.ProductID = p.ProductID INNER JOIN Production.ProductSubcategory AS ps ON p.ProductSubcategoryID = ps.ProductSubcategoryID INNER JOIN Production.ProductCategory AS pc ON ps.ProductCategoryID = pc.ProductCategoryID WHERE soh.OrderDate >= @start_date AND soh.OrderDate <= @end_date GROUP BY pc.Name ORDER BY pc.Name ASC;

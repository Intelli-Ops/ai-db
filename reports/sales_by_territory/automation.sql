-- Report:     Monthly sales by territory
-- Status:     PASSED - awaiting human review
-- Tested on:  {'start_date': '2025-03-01', 'end_date': '2025-03-31'} and held-out {'start_date': '2025-04-01', 'end_date': '2025-04-30'}
-- Written by: gemini-3.5-flash-lite on 2026-10-06, attempt 1 of 5
-- Parameters: @start_date date, @end_date date
-- Tables:     Sales.SalesOrderHeader, Sales.SalesTerritory
SELECT T.Name AS Territory, COUNT(H.SalesOrderID) AS Orders, ROUND(SUM(H.SubTotal), 2) AS Sales FROM Sales.SalesOrderHeader AS H INNER JOIN Sales.SalesTerritory AS T ON H.TerritoryID = T.TerritoryID WHERE H.OrderDate >= @start_date AND H.OrderDate < DATEADD(day, 1, @end_date) GROUP BY T.Name ORDER BY Sales DESC

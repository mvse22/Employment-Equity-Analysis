--Q1. Which cities/towns host the most employees and which province are they in?
--how many employers are the workers employed by.

SELECT TOP 10
       e.city_town,
       e.province,
       COUNT(DISTINCT f.ee_ref) AS employers,
       SUM(f.total_headcount)   AS employees
FROM   fact_workforce_profile f
JOIN   employer_year_attrs e
       ON  e.ee_ref = f.ee_ref AND e.submission_year = f.submission_year
WHERE  f.submission_year = (SELECT MAX(submission_year)
                            FROM fact_workforce_profile)
GROUP  BY e.city_town, e.province
ORDER  BY employees DESC;

--Q2. Who are the 10 highest employers and what percent are their female hires?
SELECT TOP 10
       f.ee_ref,
       COALESCE(e.dti_registration_name, d.registration_name, f.ee_ref) AS employer_name,
       e.industry_sector,
       e.province,
       SUM(f.total_headcount) AS employees,
       CAST(ROUND(100.0 * SUM(f.african_female + f.coloured_female + f.foreign_female
                         + f.indian_female + f.white_female)
             / NULLIF(SUM(f.total_headcount), 0), 1) AS DECIMAL(12,1)) AS pct_female
FROM   fact_workforce_profile f
JOIN   dim_employer d ON d.ee_ref = f.ee_ref
LEFT   JOIN employer_year_attrs e
       ON  e.ee_ref = f.ee_ref AND e.submission_year = f.submission_year
WHERE  f.submission_year = (SELECT MAX(submission_year)
                            FROM fact_workforce_profile)
GROUP  BY f.ee_ref,
          COALESCE(e.dti_registration_name, d.registration_name, f.ee_ref),
          e.industry_sector, e.province
ORDER  BY employees DESC;

--Q3.How many employers and employees are in the different sectors?
--What percentage of females are in different occupation levels
SELECT e.business_type,
       COUNT(DISTINCT f.ee_ref) AS employers,
       SUM(f.total_headcount)   AS employees,
       CAST(ROUND(100.0 * SUM(f.african_female + f.coloured_female + f.foreign_female
                         + f.indian_female + f.white_female)
             / NULLIF(SUM(f.total_headcount), 0), 1) AS DECIMAL(12,1)) AS pct_female_all_levels,
       CAST(ROUND(100.0 * SUM(CASE WHEN f.occupation_level IN ('Top management', 'Senior management')
                              THEN f.african_female + f.coloured_female + f.foreign_female
                                   + f.indian_female + f.white_female ELSE 0 END)
             / NULLIF(SUM(CASE WHEN f.occupation_level IN ('Top management', 'Senior management')
                               THEN f.total_headcount ELSE 0 END), 0), 1) AS DECIMAL(12,1)) AS pct_female_senior_leadership,
       CAST(ROUND(100.0 * SUM(CASE WHEN f.occupation_level = 'Temporary employees'
                              THEN f.total_headcount ELSE 0 END)
             / NULLIF(SUM(f.total_headcount), 0), 1) AS DECIMAL(12,1)) AS pct_temporary
FROM   fact_workforce_profile f
JOIN   employer_year_attrs e
       ON  e.ee_ref = f.ee_ref AND e.submission_year = f.submission_year
WHERE  f.submission_year = (SELECT MAX(submission_year) 
                            FROM fact_workforce_profile)
GROUP  BY e.business_type
ORDER  BY employees DESC;

--Q4. Which sector employs the highest number of foreign nationals and what percentage do
--foreign nationals make of their total employees
SELECT COALESCE(e.industry_sector, 'Unknown') AS industry_sector,
       SUM(f.foreign_female + f.foreign_male) AS foreign_nationals,
       SUM(f.total_headcount)                 AS employees,
       CAST(ROUND(100.0 * SUM(f.foreign_female + f.foreign_male)
             / NULLIF(SUM(f.total_headcount), 0), 1) AS DECIMAL(12,1)) AS pct_foreign_nationals
FROM   fact_workforce_profile f
LEFT   JOIN employer_year_attrs e
       ON  e.ee_ref = f.ee_ref AND e.submission_year = f.submission_year
WHERE  f.submission_year = (SELECT MAX(submission_year)
                            FROM fact_workforce_profile)
GROUP  BY COALESCE(e.industry_sector, 'Unknown')
ORDER  BY pct_foreign_nationals DESC;

--Q5.How many employees are there at the different employment levels
--and what percentage of the workforce does each make
SELECT occupation_level,
       SUM(total_headcount) AS no_of_employees,
       CAST(ROUND(100.0 * SUM(total_headcount) / SUM(SUM(total_headcount)) OVER (), 1) AS DECIMAL(12,1)) AS pct_of_workforce
FROM   fact_workforce_profile
WHERE  submission_year = (SELECT MAX(submission_year)
                          FROM fact_workforce_profile)
GROUP  BY occupation_level
ORDER  BY no_of_employees DESC;

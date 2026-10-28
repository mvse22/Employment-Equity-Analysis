import logging
import re
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import pyodbc
import urllib.parse
from pathlib import Path

# Configuration and logging set up
DATA_DIR = Path(r"C:\Users\mctle\OneDrive\Documents\Domain Expansion\Portfolio Work\71point4 Analyst Assingment")
META_CSV = DATA_DIR / "ee_meta.csv"
PROFILE_CSV = DATA_DIR / "ee_profile_all.csv"

SQL_SERVER = "MVSEGX\\SQLEXPRESS"
SQL_DATABASE = "Analyst_Assignment"
SQL_DRIVER = "ODBC Driver 17 for SQL Server"
Trusted_Connection = "Yes"


logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger("ee_etl")

#Handling repeated attribute names in the ee_meta.csv file
META_ATTRIBUTES = [
                    "dti_registration_name",
                    "industry_sector",
                    "seta_classification",
                    "business_type",
                    "province",
                    "city_town"
]
#Mapping of the expected column names in the ee_profile_all.csv file to the actual column names in the DataFrame
PROFILE_COLUMNS_MAPPING = {
                    "african_female": "african_female",
                     "african_male": "african_male",
                    "coloured_female": "coloured_female",
                    "coloured_male": "coloured_male",
                    "foreign_female": "foreign_female",
                    "foriegn_male": "foreign_male",
                    "indian_female": "indian_female",
                    "indian_male": "indian_male",
                    "white_female": "white_female",
                    "white_male": "white_male"
}

HEADCOUNT_COLUMNS = list(PROFILE_COLUMNS_MAPPING.values())

OCCUPATION_LEVEL_FIXES = {"Temporary" : "Temporary employees"}


#Extracting the data from the csv files
def extract_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    log.info("Extracting %s and %s", META_CSV, PROFILE_CSV)
    meta = pd.read_csv(META_CSV, dtype=str)
    profile = pd.read_csv(PROFILE_CSV, dtype=str)
    log.info("Extracted %d rows from %s and %d rows from %s", len(meta), META_CSV, len(profile), PROFILE_CSV)
    return meta, profile

#Transforming the data by cleaning and preparing it for analysis
def clean_text(series: pd.Series) -> pd.Series:
    return (
        series.astype("string").str.strip().str.replace(r"\s+", " ", regex=True).replace("", pd.NA)
    )

def transform_meta(meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = meta.copy()
    meta["ee_ref"] = clean_text(meta["ee_ref"])
    long_parts = []
    for attr in META_ATTRIBUTES:
        pattern = re.compile(rf"^{attr}_(\d{{4}}$)")
        year_cols = [c for c in meta.columns if pattern.match(c)]

        part = meta.melt(id_vars=["ee_ref"], value_vars=year_cols, var_name="col", value_name=attr)

        part["submission_year"] = part["col"].str[-4:].astype(int)
        long_parts.append(part.drop(columns="col").set_index(["ee_ref", "submission_year"]))

    #Making employer years one row
    yearly = pd.concat(long_parts, axis=1).reset_index()

    #Cleaning text attributes
    for attr in META_ATTRIBUTES:
        yearly[attr] = clean_text(yearly[attr])

    #Dropping employer years on emppty attributes
    yearly = yearly.dropna(subset=META_ATTRIBUTES, how="all")

    #Setting up table dimeensions using recent names
    latest = (
        yearly.dropna(subset=["dti_registration_name"]).sort_values(["ee_ref", "submission_year"])
        .groupby("ee_ref", as_index=False).last()[["ee_ref", "dti_registration_name"]]
        .rename(columns={"dti_registration_name": "registration_name"})

    )

    dim = meta[["ee_ref"]].drop_duplicates().merge(latest, on="ee_ref", how="left")
    log.info("Employer dimension rows: %d | Employer years rows: %d", len(dim), len(yearly))
    return dim, yearly.sort_values(["ee_ref", "submission_year"]).reset_index(drop=True)

#Fixing the column names
def transform_profile(profile: pd.DataFrame) -> pd.DataFrame:
    df = profile.copy()
    df.columns = [PROFILE_COLUMNS_MAPPING.get(c.lower(), c.lower()) for c in df.columns]

    df["ee_ref"] = clean_text(df["ee_ref"])
    df["occupation_level"] = clean_text(df["occupation_level"]).replace(OCCUPATION_LEVEL_FIXES)

    df[HEADCOUNT_COLUMNS] = df[HEADCOUNT_COLUMNS].apply(pd.to_numeric, errors="coerce") 
    bad = df[HEADCOUNT_COLUMNS].isna().any(axis=1) | (df[HEADCOUNT_COLUMNS] < 0).any(axis=1)
    if bad.any():
        log.warning("Dropping %d rows with invalid headcount values", bad.sum())
        df = df.loc[~bad]
    df[HEADCOUNT_COLUMNS] = df[HEADCOUNT_COLUMNS].astype("int64")
    df["submission_year"] = df["submission_year"].astype("int64")
    df["total_headcount"] = df[HEADCOUNT_COLUMNS].sum(axis=1)

    key = ["ee_ref","submission_year","occupation_level"]
    dupes = df.duplicated(key, keep="first")
    if dupes.any():
        log.warning("Dropping %d duplicate rows on %s, dupes.sum(), key")
        df = df[~dupes]

    columns = key + HEADCOUNT_COLUMNS + ["total_headcount"]
    return df[columns].reset_index(drop=True)


#Loading Data into an empty database created in SQL Server
DDL = """CREATE TABLE dbo.dim_employer (
    ee_ref                   VARCHAR(64)   NOT NULL PRIMARY KEY,
    registration_name        NVARCHAR(300) NULL
);
 
CREATE TABLE dbo.employer_year_attrs (
    ee_ref                 VARCHAR(64)   NOT NULL,
    submission_year        SMALLINT      NOT NULL,
    dti_registration_name  NVARCHAR(300) NULL,
    industry_sector        NVARCHAR(200) NULL,
    seta_classification    NVARCHAR(300) NULL,
    business_type          NVARCHAR(100) NULL,
    province               NVARCHAR(100) NULL,
    city_town              NVARCHAR(150) NULL,
    CONSTRAINT PK_employer_year_attrs PRIMARY KEY (ee_ref, submission_year),
    CONSTRAINT FK_attrs_employer FOREIGN KEY (ee_ref) REFERENCES dbo.dim_employer (ee_ref)
);
 
CREATE TABLE dbo.fact_workforce_profile (
    ee_ref           VARCHAR(64)   NOT NULL,
    submission_year  SMALLINT      NOT NULL,
    occupation_level NVARCHAR(200) NOT NULL,
    african_female   INT NOT NULL,
    african_male     INT NOT NULL,
    coloured_female  INT NOT NULL,
    coloured_male    INT NOT NULL,
    foreign_female   INT NOT NULL,
    foreign_male     INT NOT NULL,
    indian_female    INT NOT NULL,
    indian_male      INT NOT NULL,
    white_female     INT NOT NULL,
    white_male       INT NOT NULL,
    total_headcount  INT NOT NULL,
    CONSTRAINT PK_fact_workforce PRIMARY KEY (ee_ref, submission_year, occupation_level),
    CONSTRAINT FK_fact_employer FOREIGN KEY (ee_ref) REFERENCES dbo.dim_employer (ee_ref)
);"""
def connection_string(database: str) -> str:
    return (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;" 
)

def get_engine (database: str = None, **engine_kwargs):
    odbc = connection_string(SQL_DATABASE)
    return create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc),
        **engine_kwargs,)


def verify_database_ready() -> None:

    engine = None
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Connecting directly to SQL_DATABASE fails if it doesn't exist
            # or the Windows user has no access to it.
            tables = conn.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'"
            )).scalar()
    except Exception as exc:
        raise SystemExit(
            f"Could not connect to database '{SQL_DATABASE}' on '{SQL_SERVER}'. Check that it "
            f"exists, that SQL_SERVER/SQL_DATABASE are correct, and that your Windows login "
            f"has access.\nDetails: {exc}"
        )
    finally:
        if engine is not None:
            engine.dispose()
 
    if tables:
        raise SystemExit(
            f"Database '{SQL_DATABASE}' already contains {tables} table(s). "
            "It must be empty, so nothing was loaded."
        )
    log.info("Database '%s' exists and is empty", SQL_DATABASE)
 
 
def load(dim: pd.DataFrame, yearly: pd.DataFrame, fact: pd.DataFrame) -> None:
#Create the tables in the existing empty database and insert the data in one transaction.
    verify_database_ready() 
    # fast_executemany makes bulk inserts via pyodbc
    engine = get_engine(fast_executemany=True)
 
    #engine.begin() commits on success and rolls back everything on error
    with engine.begin() as conn:
        log.info("Creating tables")
        for statement in filter(None, (s.strip() for s in DDL.split(";"))):
            conn.execute(text(statement))
 
        # Parents first so foreign keys are satisfied
        log.info("Loading dim_employer")
        dim.to_sql("dim_employer", conn, schema="dbo", if_exists="append", index=False)
 
        log.info("Loading employer_year_attrs")
        yearly.to_sql("employer_year_attrs", conn, schema="dbo", if_exists="append",
                      index=False, chunksize=5000)
 
        log.info("Loading fact_workforce_profile")
        fact.to_sql("fact_workforce_profile", conn, schema="dbo", if_exists="append",
                    index=False, chunksize=5000)
 
    #Post load validation: compare DB row counts with what we sent
    with engine.connect() as conn:
        for name, expected in [("dim_employer", len(dim)),
                               ("employer_year_attrs", len(yearly)),
                               ("fact_workforce_profile", len(fact))]:
            actual = conn.execute(text(f"SELECT COUNT(*) FROM dbo.{name}")).scalar()
            status = "OK" if actual == expected else "MISMATCH"
            log.info("%-24s expected=%-6d loaded=%-6d %s", name, expected, actual, status)
    engine.dispose()

#Pipeline entry point
def main() -> None:
    meta_raw, profile_raw = extract_data()
    dim, yearly = transform_meta(meta_raw)
    fact = transform_profile(profile_raw)

    orphans = ~fact["ee_ref"].isin(dim["ee_ref"])
    if orphans.any():
        log.warning("Dropping %d profile rows whose ee_ref is not in meta file",orphans.sum())
        fact = fact[~orphans]

    load(dim, yearly, fact)
    log.info("ETL  complete")


if __name__ == "__main__":
    main()

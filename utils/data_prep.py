from pathlib import Path
import pandas as pd
import pandera as pa
from pandera import Column, DataFrameSchema, Check

# Schema validation
SCHEMA = DataFrameSchema(
    {
        "Sl. No.": Column(object, nullable=True),
        "State/UT": Column(str),
        "2022": Column(int, Check.ge(0)),
        "percentage": Column(float, nullable=True),
    },
    coerce=True,
)

def load_data(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = SCHEMA.validate(df, lazy=True)
    return df

def ensure_percentage_column(df: pd.DataFrame, year_col: str = "2022", pct_col: str = "percentage") -> pd.DataFrame:
    out = df.copy()
    if pct_col not in out.columns or out[pct_col].isna().any():
        total = out[year_col].sum()
        out[pct_col] = (out[year_col] / total) * 100.0
    return out

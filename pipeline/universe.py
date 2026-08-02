"""Build the analysable stock universe from the KRX listing.

Keeps KOSPI/KOSDAQ common shares. ETFs and ETNs are already absent from
FinanceDataReader's KRX listing; what we still have to strip is preferred
shares and SPACs, neither of which behaves like a momentum leader.
"""
from __future__ import annotations

import re

import pandas as pd

from . import config

# Korean tickers are six characters and the last one encodes the share class:
# common shares end in "0", preferred shares end in 5/7/9 (구형/신형) or in a
# letter such as K/L/M for the newer convertible-preferred series.
#
# The leading five characters may contain letters -- KRX's newer code format
# gives recent listings codes like 0126Z0 (삼성에피스홀딩스) or 0009K0 (에임드바이오).
# Those are ordinary common shares, so the pattern must not assume all digits.
COMMON_CODE_RE = re.compile(r"^[0-9A-Z]{5}0$")

SPAC_RE = re.compile(r"스팩|기업인수목적")


def load_universe() -> pd.DataFrame:
    """Return a DataFrame of tradable common shares with listing metadata."""
    import FinanceDataReader as fdr

    listing = fdr.StockListing("KRX")
    listing = listing[listing["Market"].isin(config.MARKETS)].copy()

    listing["is_common"] = listing["Code"].str.match(COMMON_CODE_RE)
    listing["is_spac"] = listing["Name"].str.contains(SPAC_RE, na=False)

    keep = listing[listing["is_common"] & ~listing["is_spac"]].copy()

    cols = ["Code", "Name", "Market", "Close", "Amount", "Marcap", "Stocks"]
    keep = keep[[c for c in cols if c in keep.columns]]
    keep = keep.rename(
        columns={
            "Code": "code",
            "Name": "name",
            "Market": "market",
            "Close": "close",
            "Amount": "amount",
            "Marcap": "marcap",
            "Stocks": "shares",
        }
    )
    return keep.sort_values("code").reset_index(drop=True)


if __name__ == "__main__":  # manual sanity check
    import FinanceDataReader as fdr

    raw = fdr.StockListing("KRX")
    raw = raw[raw["Market"].isin(config.MARKETS)]
    u = load_universe()
    dropped = raw[~raw["Code"].isin(u["code"])]

    print(f"raw KOSPI+KOSDAQ : {len(raw)}")
    print(f"kept (common)    : {len(u)}")
    print(f"dropped          : {len(dropped)}")
    print(u["market"].value_counts().to_dict())
    print("\n-- sample of dropped, to confirm we only lose pref/SPAC/odd codes --")
    print(dropped[["Code", "Name", "Market"]].head(25).to_string(index=False))
    print("\n-- any dropped name that looks like an ordinary company? --")
    odd = dropped[~dropped["Name"].str.contains(SPAC_RE, na=False)]
    odd = odd[~odd["Name"].str.contains("우$|우B$|우C$|[0-9]우$", regex=True, na=False)]
    print(odd[["Code", "Name"]].head(30).to_string(index=False))
    print("count of non-obvious drops:", len(odd))

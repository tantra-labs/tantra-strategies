## What it is

The opening range is the high and low of the first N bars of a session (default 3 bars, the
first 15 minutes on 5-minute data). A close beyond it is the opening-range breakout (ORB).

## How it's calculated

```
or_high = max(high of first N bars)   or_low = min(low of first N bars)
or_mid  = (or_high + or_low) / 2
```

Sessions roll at the IST date boundary. The range is not exposed until all N bars of the
session have been seen, so there is no lookahead: values are null while the window is still
forming. The breakout detector fires on the first close above or_high and the first close
below or_low in each session, at most once per side per session.

"""Bilingual string table for Grafana dashboards.

Source-string-keyed: English text is the lookup key. Missing Hebrew falls
back to English so partial translation is safe. Add entries below to extend.
"""

HE: dict[str, str] = {
    # Dashboard meta
    "ALO — Stress Analysis": "ALO — ניתוח עומסים",
    "Stress analysis by application, target, operation, and template, with overall trend.":
        "ניתוח עומסים לפי אפליקציה, יעד, פעולה ותבנית, כולל מגמה כוללת.",

    # Section labels (used in titles + column headers)
    "Application": "אפליקציה",
    "Target": "יעד",
    "Operation": "פעולה",
    "Cost Indicator": "מחוון עלות",
    "Template": "תבנית",

    # KPI / panel titles
    "ES CPU Usage": "ניצול CPU של Elasticsearch",
    "Total Stress Score": "סך ציוני העומס",
    "Dashboard Guide": "מדריך לדשבורד",

    # Templated titles — use .format(label=...) after lookup
    "Stress by {label} (Selected Period)":
        "עומס לפי {label} — בטווח שנבחר",
    "Stress by {label}": "עומס לפי {label}",

    # Section rows
    "Highest Impact": "ההשפעה הגדולה ביותר",
    "Stress Trends": "מגמות העומס",
    "Volume & Throughput": "נפח ותפוקה",
    "Response Times": "זמני תגובה",

    # Tables / bars
    "Top 10 Templates by Stress Score":
        "עשר התבניות המובילות לפי ציון העומס",
    "Top 10 Heaviest Operations":
        "עשר הפעולות הכבדות ביותר",
    "Top 10 Cost Indicators by Stress Score":
        "עשרת מחווני העלות המובילים לפי ציון העומס",

    # Volume panels
    "Request Volume": "נפח בקשות",
    "Documents Matched by Queries": "מסמכים שהוחזרו משאילתות",
    "Write Volume (Documents)": "נפח כתיבה (מסמכים)",
    "Request Size": "גודל בקשות",
    "Avg Documents per Query": "ממוצע מסמכים לשאילתה",
    "Avg Documents per Write": "ממוצע מסמכים לפעולת כתיבה",
    "Avg Request Size": "גודל בקשה ממוצע",
    "ES Latency": "השהיית Elasticsearch",

    # Column labels
    "Sum Stress Score": "סך ציון העומס",
    "Avg Stress Score": "ציון עומס ממוצע",
    "P50 ES Latency (ms)": "השהיית ES, P50 (ms)",
    "P95 ES Latency (ms)": "השהיית ES, P95 (ms)",
    "P99 ES Latency (ms)": "השהיית ES, P99 (ms)",
    "Avg Cost Indicators": "ממוצע מחווני עלות",
    "Requests": "מספר בקשות",
    "Sum Stress": "סך עומס",
    "Avg Stress": "עומס ממוצע",

    # Raw docs columns
    "Time": "זמן",
    "Request Body": "גוף הבקשה",
    "Path": "נתיב",
    "Stress": "עומס",
    "ES Latency (ms)": "השהיית ES (ms)",
    "Cost Indicators": "מחווני עלות",
    "Doc ID": "מזהה מסמך",

    # Multi-series labels
    "Avg": "ממוצע",

    # Variable labels (sidebar)
    "Cluster": "אשכול",
    "Username": "שם משתמש",
    "Client Host": "מארח לקוח",

    # Cross-link button
    "English": "English",
    "עברית": "עברית",

    # Panel descriptions — KPIs / overview
    "Sum of all stress scores in the selected time period.":
        "סך כל ציוני העומס בטווח הזמן שנבחר.",
    "Quick reference guide for examining this dashboard.":
        "מדריך מהיר לקריאת הדשבורד.",
    "Elasticsearch process CPU %. Requires prometheus profile.":
        "אחוז CPU של תהליך Elasticsearch. דורש את פרופיל ה-prometheus.",

    # Panel descriptions — pie charts (PANEL_DESCRIPTIONS["pie"][label])
    "Shows stress distribution across applicative providers. Click a slice to filter the dashboard.":
        "התפלגות העומס בין ספקי האפליקציה. לחיצה על פלח תסנן את הדשבורד.",
    "Shows stress distribution across target indices/databases. Click a slice to filter the dashboard.":
        "התפלגות העומס בין אינדקסים ובסיסי נתונים. לחיצה על פלח תסנן את הדשבורד.",
    "Shows stress distribution across operation types (search, index, bulk, etc.). Click a slice to filter.":
        "התפלגות העומס לפי סוגי פעולות (search, index, bulk וכד'). לחיצה על פלח תסנן.",
    "Stress distribution across cost indicator types. 'unflagged' = requests with no cost indicators.":
        "התפלגות העומס לפי סוגי מחווני עלות. 'unflagged' = בקשות ללא מחוונים.",
    "Shows stress distribution across request templates. Click a slice to filter the dashboard.":
        "התפלגות העומס לפי תבניות הבקשה. לחיצה על פלח תסנן את הדשבורד.",

    # Panel descriptions — time series (PANEL_DESCRIPTIONS["ts"][label])
    "Average stress score over time, broken down by applicative provider.":
        "ציון עומס ממוצע לאורך הזמן, לפי ספק האפליקציה.",
    "Average stress score over time, broken down by target index/database.":
        "ציון עומס ממוצע לאורך הזמן, לפי אינדקס או בסיס נתונים.",
    "Average stress score over time, broken down by operation type.":
        "ציון עומס ממוצע לאורך הזמן, לפי סוג הפעולה.",
    "Average stress score over time, broken down by cost indicator.":
        "ציון עומס ממוצע לאורך הזמן, לפי מחוון העלות.",
    "Average stress score over time, broken down by request template.":
        "ציון עומס ממוצע לאורך הזמן, לפי תבנית הבקשה.",

    # Panel descriptions — Highest Impact tables
    "Top 10 request templates ranked by total stress score, with latency percentiles and cost-indicator averages.":
        "עשר תבניות הבקשה המובילות לפי סך ציוני העומס, כולל אחוזוני השהיה וממוצעי מחווני עלות.",
    "Individual requests with the highest stress scores in the selected time range. Click column headers to re-sort.":
        "הבקשות עם ציוני העומס הגבוהים ביותר בטווח הזמן שנבחר. לחיצה על כותרת עמודה ממיינת מחדש.",
    "Cost indicator types ranked by total stress contribution, with latency percentiles.":
        "סוגי מחווני עלות מדורגים לפי תרומת העומס הכוללת, כולל אחוזוני השהיה.",

    # Panel descriptions — Volume & Throughput
    "Total request count over time. Dashed series = hourly summary-index fallback (survives raw-data ILM expiry).":
        "סך הבקשות לאורך הזמן. הקו המקווקו הוא נתון גיבוי מאינדקס הסיכום השעתי, לאחר שהנתונים הגולמיים פוגו ב-ILM.",
    "Total documents matched by queries. Correlates with ES CPU under queue saturation.":
        "סך המסמכים שהוחזרו משאילתות. במתאם ל-CPU של ES כאשר התור רווי.",
    "Total documents written (index / bulk / update).":
        "סך המסמכים שנכתבו (index / bulk / update).",
    "Total inbound request payload size.":
        "סך גודל הבקשות הנכנסות.",
    "Average documents matched per query — query selectivity signal.":
        "ממוצע מסמכים שהוחזרו לשאילתה — אינדיקציה לסלקטיביות השאילתה.",
    "Average documents written per operation — batch-size signal.":
        "ממוצע מסמכים שנכתבו לפעולה — אינדיקציה לגודל ה-batch.",
    "Average request payload size — per-call shape.":
        "גודל ממוצע של מטען הבקשה — צורת הבקשה הבודדת.",

    # Panel descriptions — Response Times
    "Elasticsearch response-time trend with Avg / P50 / P95 / P99 — rising P95/P99 signals tail-latency issues.":
        "מגמת זמן התגובה של Elasticsearch — ממוצע / P50 / P95 / P99. עלייה ב-P95/P99 מסמנת בעיות בקצה ההתפלגות.",
}


def tr(key: str, lang: str = "en") -> str:
    """Translate ``key`` to ``lang``. Falls back to ``key`` (English) if missing."""
    if lang == "en":
        return key
    return HE.get(key, key)

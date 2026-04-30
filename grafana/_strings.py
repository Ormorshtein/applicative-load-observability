"""Bilingual string table for Grafana dashboards.

Source-string-keyed: English text is the lookup key. Missing Hebrew falls
back to English so partial translation is safe. Add entries below to extend.
"""

HE: dict[str, str] = {
    # Dashboard meta
    "ALO — Stress Analysis": "ALO — ניתוח עומס",
    "Stress analysis by application, target, operation, and template, with overall trend.":
        "ניתוח עומס לפי אפליקציה, יעד, פעולה ותבנית, עם מגמה כללית.",

    # Section labels (used in titles + column headers)
    "Application": "אפליקציה",
    "Target": "יעד",
    "Operation": "פעולה",
    "Cost Indicator": "מחוון עלות",
    "Template": "תבנית",

    # KPI / panel titles
    "ES CPU Usage": "ניצול CPU של Elasticsearch",
    "Elasticsearch process CPU %. Requires prometheus profile.":
        "אחוז CPU של תהליך Elasticsearch. דורש פרופיל prometheus.",
    "Total Stress Score": "ציון עומס כולל",
    "Dashboard Guide": "מדריך לוח המחוונים",

    # Templated titles — use .format(label=...) after lookup
    "Stress by {label} (Selected Period)":
        "עומס לפי {label} (טווח נבחר)",
    "Stress by {label}": "עומס לפי {label}",

    # Section rows
    "Highest Impact": "השפעה גבוהה ביותר",
    "Stress Trends": "מגמות עומס",
    "Volume & Throughput": "נפח ותפוקה",
    "Response Times": "זמני תגובה",

    # Tables / bars
    "Top 10 Templates by Stress Score":
        "10 התבניות המובילות לפי ציון עומס",
    "Top 10 Heaviest Operations":
        "10 הפעולות הכבדות ביותר",
    "Top 10 Cost Indicators by Stress Score":
        "10 מחווני העלות המובילים לפי ציון עומס",

    # Volume panels
    "Request Volume": "נפח בקשות",
    "Documents Matched by Queries": "מסמכים תואמים לשאילתות",
    "Write Volume (Documents)": "נפח כתיבה (מסמכים)",
    "Request Size": "גודל בקשה",
    "ES Latency": "השהיית Elasticsearch",

    # Column labels
    "Sum Stress Score": "סכום ציוני עומס",
    "Avg Stress Score": "ממוצע ציון עומס",
    "P50 ES Latency (ms)": "P50 השהיית ES (ms)",
    "P95 ES Latency (ms)": "P95 השהיית ES (ms)",
    "P99 ES Latency (ms)": "P99 השהיית ES (ms)",
    "Avg Cost Indicators": "ממוצע מחווני עלות",
    "Requests": "בקשות",
    "Sum Stress": "סכום עומס",
    "Avg Stress": "ממוצע עומס",

    # Raw docs columns
    "Time": "זמן",
    "Request Body": "גוף בקשה",
    "Path": "נתיב",
    "Stress": "עומס",
    "ES Latency (ms)": "השהיית ES (ms)",
    "Cost Indicators": "מחווני עלות",

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
        "סכום כלל ציוני העומס בטווח הזמן הנבחר.",
    "Quick reference guide for examining this dashboard.":
        "מדריך מקוצר לבחינת לוח המחוונים.",

    # Panel descriptions — pie charts (PANEL_DESCRIPTIONS["pie"][label])
    "Shows stress distribution across applicative providers. Click a slice to filter the dashboard.":
        "מציג התפלגות עומס בין ספקי האפליקציה. לחיצה על פלח תסנן את הלוח.",
    "Shows stress distribution across target indices/databases. Click a slice to filter the dashboard.":
        "מציג התפלגות עומס בין אינדקסים/מסדי נתונים. לחיצה על פלח תסנן את הלוח.",
    "Shows stress distribution across operation types (search, index, bulk, etc.). Click a slice to filter.":
        "מציג התפלגות עומס בין סוגי פעולה (search, index, bulk וכו'). לחיצה על פלח תסנן.",
    "Stress distribution across cost indicator types. 'unflagged' = requests with no cost indicators.":
        "התפלגות עומס בין סוגי מחווני עלות. 'unflagged' = בקשות ללא מחווני עלות.",
    "Shows stress distribution across request templates. Click a slice to filter the dashboard.":
        "מציג התפלגות עומס בין תבניות בקשה. לחיצה על פלח תסנן את הלוח.",

    # Panel descriptions — time series (PANEL_DESCRIPTIONS["ts"][label])
    "Average stress score over time, broken down by applicative provider.":
        "ציון עומס ממוצע לאורך זמן, מפולח לפי ספק אפליקציה.",
    "Average stress score over time, broken down by target index/database.":
        "ציון עומס ממוצע לאורך זמן, מפולח לפי אינדקס/מסד נתונים.",
    "Average stress score over time, broken down by operation type.":
        "ציון עומס ממוצע לאורך זמן, מפולח לפי סוג פעולה.",
    "Average stress score over time, broken down by cost indicator.":
        "ציון עומס ממוצע לאורך זמן, מפולח לפי מחוון עלות.",
    "Average stress score over time, broken down by request template.":
        "ציון עומס ממוצע לאורך זמן, מפולח לפי תבנית בקשה.",

    # Panel descriptions — Highest Impact tables
    "Top 10 request templates ranked by total stress score, with latency percentiles and cost-indicator averages.":
        "10 תבניות הבקשה המובילות לפי סכום ציוני העומס, עם אחוזוני השהיה וממוצעי מחווני עלות.",
    "Individual requests with the highest stress scores in the selected time range. Click column headers to re-sort.":
        "הבקשות הבודדות עם ציוני העומס הגבוהים ביותר בטווח הזמן הנבחר. לחיצה על כותרת עמודה לסידור מחדש.",
    "Cost indicator types ranked by total stress contribution, with latency percentiles.":
        "סוגי מחווני עלות מדורגים לפי תרומת העומס הכוללת, עם אחוזוני השהיה.",

    # Panel descriptions — Volume & Throughput
    "Total request count over time. Dashed series = hourly summary-index fallback (survives raw-data ILM expiry).":
        "סך הבקשות לאורך זמן. סדרה מקווקוות = גיבוי מאינדקס סיכום שעתי (שורד פקיעת ILM של נתונים גולמיים).",
    "Total documents matched by queries. Correlates with ES CPU under queue saturation.":
        "סך המסמכים התואמים לשאילתות. מתאם עם CPU של ES בהיתקלות בעומס תור.",
    "Total documents written (index / bulk / update).":
        "סך המסמכים שנכתבו (index / bulk / update).",
    "Total inbound request payload size.":
        "סך גודל מטען הבקשות הנכנסות.",

    # Panel descriptions — Response Times
    "Elasticsearch response-time trend with Avg / P50 / P95 / P99 — rising P95/P99 signals tail-latency issues.":
        "מגמת זמן תגובה של Elasticsearch עם ממוצע / P50 / P95 / P99 — עלייה ב-P95/P99 מצביעה על בעיות השהיית קצה.",
}


def tr(key: str, lang: str = "en") -> str:
    """Translate ``key`` to ``lang``. Falls back to ``key`` (English) if missing."""
    if lang == "en":
        return key
    return HE.get(key, key)

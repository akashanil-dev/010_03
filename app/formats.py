"""File types TallyTime accepts. Kept apart from parsing.py so the web app does not load Docling."""

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
OFFICE_TYPES = {".xlsx", ".xls", ".ods", ".docx", ".doc", ".odt", ".csv"}
SUPPORTED = {".pdf"} | IMAGE_TYPES | OFFICE_TYPES
FORMAT_LABEL = {".xlsx": "Excel", ".xls": "Excel", ".ods": "Spreadsheet", ".docx": "Word", ".doc": "Word",
                ".odt": "Document", ".csv": "CSV"}

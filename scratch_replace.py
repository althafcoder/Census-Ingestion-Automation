import os

filepath = r"c:\Users\INT002\Census Ingestion Automation\Frontend\src\routes\index.tsx"

with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacements = [
    ('Automated Renewal Processing', 'Census Ingestion Automation'),
    ('carrier benefit renewal rates', 'carrier benefit rates'),
    ('renewal invoice', 'invoice'),
    ('renewal census', 'census'),
    ('Renewal Summary', 'Summary'),
    ('Processing renewal', 'Processing'),
    ('Process Renewal', 'Process'),
    ('`renewal-${Date.now()}.xlsx`', '`ingested-census-${Date.now()}.xlsx`'),
    ('Renewal v2 Active', 'Ingestion v2 Active'),
    ('Renewal Invoice', 'Invoice'),
    ('Renewal Results', 'Results'),
    ('Structured renewal summary', 'Structured summary'),
    ('Renewal generated', 'Census generated'),
    ('renewal results', 'results'),
    ('Renewal Pipeline', 'Pipeline'),
    ('RenewalPage', 'IngestionPage'),
    ('interface RenewalResult', 'interface IngestionResult'),
    ('RenewalResult', 'IngestionResult')
]

for old, new in replacements:
    text = text.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Done!")

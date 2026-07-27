import os
import time
import argparse
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import the existing pipeline logic
import main
import config

app = FastAPI(title="Census Ingestion API")

# Allow CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist
config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Mount the output directory so the frontend can download generated files
app.mount("/output", StaticFiles(directory=str(config.OUTPUT_DIR)), name="output")

@app.post("/process")
def process_renewal(census: UploadFile = File(...), invoice: UploadFile = File(...)):
    # Use the exact filenames uploaded by the user
    census_path = config.INPUT_DIR / census.filename
    invoice_path = config.INPUT_DIR / invoice.filename

    # Save uploaded files
    with open(census_path, "wb") as f:
        f.write(census.file.read())
    
    with open(invoice_path, "wb") as f:
        f.write(invoice.file.read())

    # Define output files for this run using the original invoice name
    invoice_stem = Path(invoice.filename).stem
    prefix = invoice_stem
    output_filled = config.OUTPUT_DIR / f"{prefix}_Filled.xlsx"
    report_json = config.OUTPUT_DIR / f"{prefix}_report.json"
    report_csv = config.OUTPUT_DIR / f"{prefix}_report.csv"
    pdf_extracted = config.EXTRACTED_DIR / f"{prefix}_pdf_extracted.xlsx"
    census_extracted = config.EXTRACTED_DIR / f"{prefix}_census_extracted.xlsx"

    # Construct the arguments expected by main.run
    args = argparse.Namespace(
        pdf=[invoice_path],
        census=census_path,
        template=config.DEFAULT_TEMPLATE_XLSX,
        output=output_filled,
        report_json=report_json,
        report_csv=report_csv,
        pdf_extracted=pdf_extracted,
        census_extracted=census_extracted,
    )

    # Run the pipeline
    try:
        report = main.run(args)
    except Exception as e:
        print(f"Error during processing: {e}")
        return {"error": str(e)}

    # Format the summary for the frontend
    summary = [
        {"label": "Total Members", "value": str(report.get("total_records", 0))},
        {"label": "Exact Matches", "value": str(report.get("exact_matches", 0))},
        {"label": "Discrepancies", "value": str(report.get("records_with_discrepancies", 0))},
    ]

    # Return the expected JSON payload
    return {
        "downloadUrl": f"http://localhost:8000/output/{output_filled.name}",
        "filename": output_filled.name,
        "summary": summary
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

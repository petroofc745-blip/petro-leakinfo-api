from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime
import duckdb
import urllib.parse
import requests
import tempfile
import os

app = FastAPI()

EXPIRY_DATE = "2026-09-28"

LANDING_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hitek Data Gateway - LIVE</title>
    <style>
        body { margin: 0; overflow: hidden; background-color: #050505; color: #00ffcc; font-family: 'Courier New', Courier, monospace; }
        #canvas-container { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: -1; }
        .overlay { 
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); 
            text-align: center; background: rgba(10, 10, 10, 0.85); padding: 50px; 
            border: 1px solid #00ffcc; border-radius: 12px; box-shadow: 0 0 30px rgba(0, 255, 204, 0.3); 
            backdrop-filter: blur(5px);
        }
        h1 { margin: 0 0 15px 0; font-size: 3.5em; text-transform: uppercase; letter-spacing: 6px; text-shadow: 0 0 15px #00ffcc; }
        p { font-size: 1.2em; margin: 8px 0; color: #ccc; }
        .highlight { color: #00ffcc; font-weight: bold; }
        .status-box { 
            margin-top: 30px; font-weight: bold; padding: 15px; 
            border-radius: 8px; background: rgba(0, 255, 204, 0.1); 
            border: 1px solid rgba(0, 255, 204, 0.5);
            font-size: 1.1em;
        }
        .blinking { animation: blinker 1.5s linear infinite; display: inline-block; }
        @keyframes blinker { 50% { opacity: 0; } }
    </style>
</head>
<body>
    <div id="canvas-container"></div>
    <div class="overlay">
        <h1>SYSTEM ONLINE</h1>
        <p>API Gateway is <span class="highlight">Active & Secured</span></p>
        <p>Parquet Cloud Engine: <span class="highlight">Connected</span></p>
        <div class="status-box">
            <span class="blinking" style="color: #00ffcc;">●</span> HTTP 200 OK - LISTENING FOR QUERIES
        </div>
    </div>
</body>
</html>
"""

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "status": "rejected",
                "message": "Invalid endpoint. STRICTLY use /FetchData?Number=XXXXXXXXXX",
                "Developer": "@coderpetro"
            }
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "Developer": "@coderpetro"}
    )

@app.get("/", response_class=HTMLResponse)
def root_landing_page():
    return HTMLResponse(content=LANDING_PAGE_HTML, status_code=200)

@app.get("/ping")
def ping_server():
    return {"status": "alive", "message": "Server is awake"}

@app.get("/FetchData")
def fetch_data(Number: str = Query(None)):
    try:
        expiry_date_obj = datetime.strptime(EXPIRY_DATE, "%Y-%m-%d")
        current_date = datetime.now()
        
        if current_date > expiry_date_obj:
            return JSONResponse(
                status_code=403,
                content={
                    "status": "expired",
                    "message": "Service subscription has expired. Please contact the developer.",
                    "Expiry_Date": EXPIRY_DATE,
                    "Developer": "@coderpetro"
                }
            )
        
        days_remaining = (expiry_date_obj - current_date).days
    except Exception:
        days_remaining = "Unknown"

    if not Number or not Number.isdigit() or len(Number) < 10 or len(Number) > 15:
        return JSONResponse(
            status_code=400,
            content={
                "status": "rejected",
                "message": "Invalid parameter. STRICTLY use /FetchData?Number=XXXXXXXXXX",
                "Developer": "@coderpetro"
            }
        )
    
    last_digit = Number[-1]
    
    # Direct URLs with proper space encoding for requests download fallback
    raw_primary_url = f"https://huggingface.co/datasets/CutehackX/hitek-data-bucket/resolve/main/final master shard {last_digit}.parquet"
    raw_alt_url = f"https://huggingface.co/datasets/CutehackX/hitek-data-bucket/resolve/main/alt master shard {last_digit}.parquet"
    
    primary_url = urllib.parse.quote(raw_primary_url, safe=":/._-")
    alt_url = urllib.parse.quote(raw_alt_url, safe=":/._-")
    
    primary_tmp_path = None
    alt_tmp_path = None
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # Download primary parquet file locally via requests to bypass direct HTTP duckdb space issue
        res_primary = requests.get(primary_url, headers=headers, stream=True)
        if res_primary.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as tmp1:
                for chunk in res_primary.iter_content(chunk_size=8192):
                    tmp1.write(chunk)
                primary_tmp_path = tmp1.name

        # Download alt parquet file locally via requests
        res_alt = requests.get(alt_url, headers=headers, stream=True)
        if res_alt.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as tmp2:
                for chunk in res_alt.iter_content(chunk_size=8192):
                    tmp2.write(chunk)
                alt_tmp_path = tmp2.name

        con = duckdb.connect(database=':memory:', read_only=False)
        
        query_parts = []
        if primary_tmp_path and os.path.exists(primary_tmp_path):
            query_parts.append(f"SELECT *, 'Main' AS _record_type FROM read_parquet('{primary_tmp_path}') WHERE mobile = '{Number}'")
        
        if alt_tmp_path and os.path.exists(alt_tmp_path):
            query_parts.append(f"SELECT *, 'Alt' AS _record_type FROM read_parquet('{alt_tmp_path}') WHERE alt = '{Number}'")
            
        if not query_parts:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": "Failed to download parquet shards from cloud repository.",
                    "Developer": "@coderpetro"
                }
            )
            
        query = " UNION ALL ".join(query_parts)
        
        raw_results = con.execute(query).df().to_dict(orient="records")
        con.close()
        
        main_records = []
        alt_records = []
        
        for row in raw_results:
            rec_type = row.pop('_record_type')
            if rec_type == 'Main':
                main_records.append(row)
            else:
                alt_records.append(row)
                
        # Clean up temp files
        if primary_tmp_path and os.path.exists(primary_tmp_path):
            os.remove(primary_tmp_path)
        if alt_tmp_path and os.path.exists(alt_tmp_path):
            os.remove(alt_tmp_path)
        
        if not main_records and not alt_records:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found", 
                    "phone": Number,
                    "Expiry_Date": EXPIRY_DATE,
                    "Days_Remaining": days_remaining,
                    "Developer": "@coderpetro"
                }
            )
            
        return {
            "status": "success", 
            "Data": {
                "Main_Records": main_records,
                "Alt_Records": alt_records
            },
            "Subscription": {
                "Expiry_Date": EXPIRY_DATE,
                "Days_Remaining": days_remaining
            },
            "Developer": "@coderpetro"
        }
        
    except Exception as e:
        if primary_tmp_path and os.path.exists(primary_tmp_path):
            os.remove(primary_tmp_path)
        if alt_tmp_path and os.path.exists(alt_tmp_path):
            os.remove(alt_tmp_path)
            
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Database processing error: {str(e)}",
                "Developer": "@coderpetro"
            }
        )

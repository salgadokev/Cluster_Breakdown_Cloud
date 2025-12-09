from flask import Flask, render_template, request, redirect, url_for
import pandas as pd
import numpy as np 
import re
import os
import io
import datetime

from google.cloud import storage
from google.cloud import firestore

app = Flask(__name__)

# --- GCP Configuration ---
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('GCP_BUCKET_NAME', 'cost-reports')

# Initialize GCS and Firestore clients
storage_client = storage.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)
db = firestore.Client(project=PROJECT_ID, database='cluster-breakdown')
collection_name = "costReportLog"


# --- HELPER FUNCTION ---
def _get_full_parsed_df(filename):
    """Downloads CSV from GCS, parses it, and returns processed DataFrame."""
    blob = bucket.blob(filename)
    data = blob.download_as_bytes()
    stream = io.BytesIO(data)
    df = pd.read_csv(stream)

    df.columns = df.columns.str.strip()
    
    possible_cols = ['Deployment name', 'Cluster Name', 'Cluster', 'ClusterName']
    cluster_col = next((c for c in possible_cols if c in df.columns), None)
    if not cluster_col:
        df['Deployment name'] = 'Unknown' # Fallback
        cluster_col = 'Deployment name'
    if cluster_col != 'Deployment name':
        df['Deployment name'] = df[cluster_col]
        
    if 'SKU Name' in df.columns:
        parts = df['SKU Name'].str.split('_', expand=True, n=4)
        for i in range(5):
            if i not in parts.columns:
                parts[i] = None
        
        parts.columns = ['Tier', 'SKU_Code_Full', 'Region', 'Size_MB', 'Nodes']
        df = pd.concat([df, parts], axis=1)

        sku_parts = df['SKU_Code_Full'].str.split('.', expand=True)
        df['Provider'] = sku_parts.get(0, 'Unknown')
        df['Edition'] = sku_parts.get(1, 'Unknown')
        df['SKU Code'] = df['SKU_Code_Full'].str.split('.', n=2).str[2].fillna('Unknown')
        
        df['Size in GB'] = pd.to_numeric(df['Size_MB'], errors='coerce').fillna(0) / 1024
        df['Number of Nodes'] = pd.to_numeric(df['Nodes'], errors='coerce').fillna(0).astype(int)
        
        df['Size in GB'] = np.where(
            (df['Size in GB'] > 64) & (df['Number of Nodes'] > 0),
            df['Size in GB'] / df['Number of Nodes'],
            df['Size in GB']
        )
        df['Size in GB'] = df['Size in GB'].round(0).astype(int)
    else:
        df['Tier'] = 'Unknown'
        df['Provider'] = 'Unknown'
        df['Edition'] = 'Unknown'
        df['SKU Code'] = 'Unknown'
        df['Region'] = 'Unknown'
        df['Size in GB'] = 0
        df['Number of Nodes'] = 0

    df['Component'] = df.get('Usage type', 'Unknown').astype(str).fillna('Unknown').str.strip()
    df = df[df['Component'].str.lower() == 'ram hours'].copy() 
    
    df['Cost per Hour'] = pd.to_numeric(df['Unit price'], errors='coerce').fillna(0)
    df['Cost per Day'] = df['Cost per Hour'] * 24
    df['Cost per Year'] = df['Cost per Day'] * 365

    preferred_order = [
        'Deployment name', 'Tier', 'Provider', 'Edition', 'SKU Code', 'Region', 
        'Size in GB', 'Number of Nodes', 
        'Cost per Hour', 'Cost per Day', 'Cost per Year' 
    ]
    final_columns = [c for c in preferred_order if c in df.columns]
    
    return df[final_columns]


@app.route('/')
def index():
    """Serves the main upload page."""
    return render_template('upload.html')


@app.route('/dashboard/<filename>')
def dashboard(filename):
    """Shows the dashboard for a SINGLE file."""
    try:
        master_df = _get_full_parsed_df(filename)

        try:
            doc = db.collection(collection_name).document(filename).get()
            display_name = doc.get('display_name', filename) if doc.exists else filename
        except Exception as e:
            print(f"Could not retrieve display_name from Firestore: {e}")
            display_name = filename

        total_yearly_cost = master_df['Cost per Year'].sum()

        # Pie Chart: Top 5 By Deployment
        by_deployment = master_df.groupby('Deployment name')['Cost per Year'].sum().round(2)
        by_deployment = by_deployment[by_deployment > 0].sort_values(ascending=False)
        
        top_5 = by_deployment.head(5).copy()
        others_sum = by_deployment.iloc[5:].sum()
        
        if others_sum > 0:
            top_5['Others'] = others_sum
            
        pie_labels = top_5.index.tolist()
        pie_data = top_5.values.tolist()

        # Bar Chart: By Provider
        by_provider = master_df.groupby('Provider')['Cost per Year'].sum().round(2)
        by_provider = by_provider[by_provider > 0]
        bar_labels = by_provider.index.tolist()
        bar_data = by_provider.values.tolist()

        return render_template('dashboard.html',
                               total_yearly_cost=total_yearly_cost,
                               pie_labels=pie_labels,
                               pie_data=pie_data,
                               bar_labels=bar_labels,
                               bar_data=bar_data,
                               cluster_col_name='Deployment name',
                               display_name=display_name,
                               filename=filename
                               )

    except Exception as e:
        print(f"Error generating dashboard for {filename}: {e}")
        return f"Error generating dashboard: {e}", 500


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles file uploads, saves to GCS, and logs to Firestore."""
    if 'file' not in request.files:
        return "No file part", 400
    
    file = request.files['file']
    account_name = request.form.get('account_name', 'UnknownAccount')

    if file.filename == '':
        return "No selected file", 400
        
    if file:
        filename = file.filename
        
        try:
            blob = bucket.blob(filename)
            blob.upload_from_string(file.read(), content_type='text/csv')
        except Exception as e:
            print(f"Error uploading to GCS: {e}")
            return "File upload to GCS failed", 500

        try:
            match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
            extracted_date = match.group(1) if match else 'NoDate'
            
            display_name = f"{account_name}_{extracted_date}"
            upload_timestamp = datetime.datetime.utcnow().isoformat()

            log_data = {
                'account_name': account_name,
                'extracted_date': extracted_date,
                'display_name': display_name,
                'upload_timestamp': upload_timestamp
            }

            db.collection(collection_name).document(filename).set(log_data, merge=True)
        except Exception as e:
            print(f"Error logging to Firestore: {e}")
            return "File logging failed", 500

        return redirect(url_for('select_deployment', filename=filename))
        
    return "File upload failed", 500


@app.route('/list')
def list_uploads():
    """Shows a page listing all uploaded files from Firestore."""
    uploads_list = []
    try:
        docs = db.collection(collection_name).stream()
        uploads_list = [doc.to_dict() for doc in docs]
        uploads_list = sorted(
            uploads_list, 
            key=lambda x: x.get('upload_timestamp', ''), 
            reverse=True
        )
    except Exception as e:
        print(f"Error reading from Firestore: {e}")
        
    return render_template('list.html', uploads=uploads_list)


@app.route('/select/<filename>')
def select_deployment(filename):
    """Shows a list of unique 'Deployment name' values from the GCS CSV."""
    try:
        blob = bucket.blob(filename)
        data = blob.download_as_bytes()
        stream = io.BytesIO(data)
        df = pd.read_csv(stream)

        df.columns = df.columns.str.strip()
        possible_cols = ['Deployment name', 'Cluster Name', 'Cluster', 'ClusterName']
        cluster_col = next((c for c in possible_cols if c in df.columns), None)

        if not cluster_col:
            df['__Default_Deployment__'] = 'All Data'
            cluster_col = '__Default_Deployment__'

        deployments = df[cluster_col].dropna().unique().tolist()

        return render_template(
            'select.html',
            deployments=deployments,
            filename=filename,
            cluster_col=cluster_col
        )
    except Exception as e:
        return f"Error processing file from GCS: {e}", 500


@app.route('/report/<filename>/<cluster_col>/<deployment>')
def report(filename, cluster_col, deployment):
    """Parses the GCS CSV and displays the cost report."""
    try:
        blob = bucket.blob(filename)
        data = blob.download_as_bytes()
        stream = io.BytesIO(data)
        df = pd.read_csv(stream)

        df.columns = df.columns.str.strip()

        if cluster_col in df.columns:
            df = df[df[cluster_col] == deployment].copy()
        
        if 'SKU Name' in df.columns:
            parts = df['SKU Name'].str.split('_', expand=True, n=4)
            for i in range(5):
                if i not in parts.columns:
                    parts[i] = None
            
            parts.columns = ['Tier', 'SKU_Code_Full', 'Region', 'Size_MB', 'Nodes']
            df = pd.concat([df, parts], axis=1)

            sku_parts = df['SKU_Code_Full'].str.split('.', expand=True)
            df['Provider'] = sku_parts.get(0, 'Unknown')
            df['Edition'] = sku_parts.get(1, 'Unknown')
            df['SKU Code'] = df['SKU_Code_Full'].str.split('.', n=2).str[2].fillna('Unknown')
            
            df['Size in GB'] = pd.to_numeric(df['Size_MB'], errors='coerce').fillna(0) / 1024
            df['Number of Nodes'] = pd.to_numeric(df['Nodes'], errors='coerce').fillna(0).astype(int)
            
            df['Size in GB'] = np.where(
                (df['Size in GB'] > 64) & (df['Number of Nodes'] > 0),
                df['Size in GB'] / df['Number of Nodes'],
                df['Size in GB']
            )
            df['Size in GB'] = df['Size in GB'].round(0).astype(int)
        else:
            df['Tier'] = 'Unknown'
            df['Provider'] = 'Unknown'
            df['Edition'] = 'Unknown'
            df['SKU Code'] = 'Unknown'
            df['Region'] = 'Unknown'
            df['Size in GB'] = 0
            df['Number of Nodes'] = 0

        df['Component'] = df.get('Usage type', 'Unknown').astype(str).fillna('Unknown').str.strip()
        df = df[df['Component'].str.lower() == 'ram hours'].copy() 
        
        df['Cost per Hour'] = pd.to_numeric(df['Unit price'], errors='coerce').fillna(0)
        df['Cost per Day'] = df['Cost per Hour'] * 24
        df['Cost per Year'] = df['Cost per Day'] * 365
        df['Total Cost (Period)'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)

        totals = {
            'hour': df['Cost per Hour'].sum(),
            'day': df['Cost per Day'].sum(),
            'year': df['Cost per Year'].sum() 
        }

        preferred_order = [
            'Tier', 'Provider', 'Edition', 'SKU Code', 'Region', 
            'Size in GB', 'Number of Nodes', 
            'Cost per Hour', 'Cost per Day', 'Cost per Year' 
        ]
        
        final_columns = [c for c in preferred_order if c in df.columns]
        df_final = df[final_columns]
        
        display_name = deployment
        try:
            doc = db.collection(collection_name).document(filename).get()
            display_name = doc.get('display_name', deployment) if doc.exists else deployment
        except Exception as e:
            print(f"Could not retrieve display_name from Firestore: {e}")

        return render_template(
            'report.html',
            deployment=deployment,
            display_name=display_name,
            rows=df_final.to_dict(orient='records'), 
            columns=final_columns, 
            totals=totals,
            filename=filename
        )
    except Exception as e:
        return f"Error generating report: {e}", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
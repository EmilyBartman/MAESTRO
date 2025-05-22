# -*- coding: utf-8 -*-
# STREAMLIT DEPLOYMENT VERSION (SECURE DISCLAIMER ADDED)

import os
import re
import io
import json
import plotly.graph_objects as go
import pandas as pd
from collections import defaultdict
from PIL import Image
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=pd.errors.ParserWarning)

# === SECURITY DISCLAIMER ===
st.warning("⚠️ DO NOT upload or enter classified or sensitive national security information into this application. This prototype is not authorized for handling classified data.", icon="🔐")

load_dotenv()
IFI_API_KEY = os.getenv("IFI_API_KEY")

for folder in ['historical_documents', 'risks_document', 'target_document', 'outputs', 'local_program_data']:
    Path(folder).mkdir(parents=True, exist_ok=True)

# === Normalization and Matching ===

def normalize_units(value):
    if isinstance(value, str):
        value = value.replace("µ", "u").replace("Ω", "ohm").replace("k", "000").lower()
    return str(value).strip()

def within_tolerance(expected, actual, tolerance=0.05):
    try:
        expected_val = float(expected)
        actual_val = float(actual)
        return abs(expected_val - actual_val) / expected_val <= tolerance
    except:
        return False

def match_component_to_spec(component_data, sae_specs, user_inputs):
    for spec in sae_specs:
        match = True
        reasons = []
        for key in user_inputs:
            spec_val = normalize_units(spec.get(key, ""))
            comp_val = normalize_units(component_data.get(key, ""))
            user_val = normalize_units(user_inputs[key])

            if not comp_val or not spec_val:
                match = False
                reasons.append(f"Missing key: {key} in component or spec.")
                continue

            if spec_val != user_val:
                match = False
                reasons.append(f"Mismatch: user required {key} = {user_val}, SAE has {spec_val}")

            if re.search(r"\d", comp_val) and re.search(r"\d", spec_val):
                if not within_tolerance(spec_val, comp_val):
                    match = False
                    reasons.append(f"Out of tolerance: {key} component={comp_val} spec={spec_val}")

        if match:
            return True, f"Component matches SAE specification: {spec.get('id', 'N/A')}"
    return False, f"No SAE spec match found. Issues: {'; '.join(reasons)}"

@st.cache_data(show_spinner=False)
def load_specs_from_file(file_path):
    ext = file_path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(file_path).to_dict(orient="records")
    elif ext == ".json":
        return json.load(open(file_path))
    else:
        raise ValueError("Unsupported file type for specs")

@st.cache_data(show_spinner=False)
def load_component_file(file):
    return pd.read_csv(file)

def process_bulk_components(component_df, sae_specs, user_inputs):
    def evaluate_row(row):
        component_data = row.to_dict()
        is_match, reason = match_component_to_spec(component_data, sae_specs, user_inputs)
        summary = generate_component_summary(component_data, is_match, reason)
        alternatives = suggest_alternatives(component_data, sae_specs) if not is_match else []
        return {
            "component": component_data,
            "match": is_match,
            "reason": reason,
            "summary": summary,
            "alternatives": alternatives,
            "risk_reduction": 0 if not is_match else 100
        }
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(evaluate_row, [row for _, row in component_df.iterrows()]))
    return results

def save_program_data(program_name, data):
    save_path = Path("local_program_data") / f"{program_name}.json"
    with open(save_path, "w") as f:
        json.dump(data, f, indent=2)

def load_program_data(program_name):
    load_path = Path("local_program_data") / f"{program_name}.json"
    if not load_path.exists():
        return {}
    with open(load_path, "r") as f:
        return json.load(f)

def generate_component_summary(component, match, reason):
    if match:
        return (f"Component {component.get('part_number', 'N/A')} meets all program and SAE specifications. "
                f"Use is recommended with 100% risk coverage achieved. Reason: {reason}.")
    else:
        return (f"Component {component.get('part_number', 'N/A')} does not meet required specifications. "
                f"Risk coverage remains at 0%. Issues: {reason}.")

def suggest_alternatives(component, sae_specs):
    candidates = []
    for spec in sae_specs:
        differences = []
        for k in component:
            if k in spec and normalize_units(component[k]) != normalize_units(spec[k]):
                differences.append((k, component[k], spec[k]))
        if len(differences) <= 2:
            candidates.append({"spec": spec, "differences": differences})
    return candidates

# === Streamlit UI ===

st.sidebar.header("Component Requirement Inputs")
user_inputs = {}
input_keys = ["type", "value", "tolerance", "voltage", "package", "temp_rating"]
for key in input_keys:
    user_val = st.sidebar.text_input(f"Required {key.title()}:", "")
    if user_val.strip():
        user_inputs[key] = user_val.strip()

st.sidebar.markdown("---")
st.sidebar.write("User specs must support SAE compliance — never override.")

st.title("📦 Component Risk Evaluator Prototype")
spec_file = st.file_uploader("Upload SAE Specs File (CSV/JSON):", type=["csv", "json"])
component_file = st.file_uploader("Upload Component List File (CSV):", type=["csv"])
program_name = st.text_input("Program Name", "demo_program")

if st.button("🔍 Run Evaluation"):
    if spec_file and component_file:
        try:
            spec_path = Path("sae_temp." + spec_file.name.split(".")[-1])
            with open(spec_path, "wb") as f:
                f.write(spec_file.getvalue())

            sae_specs = load_specs_from_file(spec_path)
            component_df = load_component_file(component_file)

            results = process_bulk_components(component_df, sae_specs, user_inputs)
            save_program_data(program_name, results)

            for res in results:
                st.markdown("---")
                st.markdown(res["summary"])
                if not res["match"] and res["alternatives"]:
                    st.markdown("**🔁 Suggested Alternatives:**")
                    for alt in res["alternatives"]:
                        st.json(alt)

            st.download_button("📤 Export Results (JSON)", json.dumps(results, indent=2), file_name=f"{program_name}_results.json")
            txt_summary = "\n\n".join(r['summary'] for r in results)
            st.download_button("📄 Export Summary (TXT)", txt_summary, file_name=f"{program_name}_results.txt")

        except Exception as e:
            st.error(f"⚠️ Error during processing: {e}")
    else:
        st.warning("Please upload both spec and component files.")

# === Program History Loader ===
st.markdown("---")
st.subheader("📁 Load Previous Program")
all_programs = sorted([f.stem for f in Path("local_program_data").glob("*.json")])
if all_programs:
    selected_program = st.selectbox("Select a saved program:", all_programs)
    if st.button("🔄 Load Program"):
        data = load_program_data(selected_program)
        for entry in data:
            st.markdown("---")
            st.markdown(entry['summary'])
            if not entry['match'] and entry['alternatives']:
                st.markdown("**🔁 Alternatives Suggested:**")
                for alt in entry['alternatives']:
                    st.json(alt)

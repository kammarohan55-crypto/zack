# FHIR R4 Document Mapper - Example Usage

This document demonstrates how to use the FHIR R4 Document Mapper to convert clinical documents into FHIR Bundles.

## Supported Document Types

1. **Medical Report** - Diseases, Medications, Dosages, Procedures  
2. **Lab Report** - Laboratory test results  
3. **Discharge Summary** - Diagnoses, Discharge outcome, Instructions  
4. **Admission Slip** - Admission reason, Department  

## Example Usage

### Medical Report

```python
from document_mapper import MedicalReportMapper

data = {
    "PII": {
        "Name": "John Doe",
        "DOB": "1980-05-15",
        "ID": "MRN12345",
        "Date": "2025-12-15"
    },
    "Disease_disorder": ["Hypertension", "Type 2 Diabetes"],
    "Medication": ["Metformin", "Lisinopril"],
    "Dosage": ["500mg twice daily", "10mg once daily"],
    "Procedure": ["Blood glucose monitoring"]
}

mapper = MedicalReportMapper()
fhir_bundle_json = mapper.map_to_fhir(data)
```

### Lab Report

```python
from document_mapper import LabReportMapper

data = {
    "PII": {
        "Name": "Alice Johnson",
        "DOB": "1975-03-22",
        "ID": "LAB98765",
        "Date": "2025-12-20"
    },
    "Lab_Tests": [
        {
            "Name": "Hemoglobin",
            "Value": "13.5",
            "Unit": "g/dL",
            "Reference_Range": "12.0-16.0 g/dL"
        }
    ]
}

mapper = LabReportMapper()
fhir_bundle_json = mapper.map_to_fhir(data)
```

### Using the API Endpoint

```bash
curl -X POST http://localhost:5000/api/v1/map/document \
  -H "Content-Type: application/json" \
  -d '{
    "document_type": "Medical Report",
    "data": {
      "PII": {
        "Name": "John Doe",
        "ID": "MRN12345"
      },
      "Disease_disorder": ["Hypertension"]
    }
  }'
```

## FHIR Compliance

✅ **Diseases** → `Condition` resource (NOT Observation)  
✅ **Medications** → `MedicationStatement` resource (NOT Observation)  
✅ **Lab Tests** → `Observation` resource ONLY  
✅ **Procedures** → `Procedure` resource  
✅ **Admission/Discharge** → `Encounter` resource  
✅ All resources reference Patient via `subject.reference`  
✅ Bundle type is `transaction`  

## Resource Mapping

| Input Field | FHIR Resource Type | Notes |
|------------|-------------------|-------|
| PII | Patient | Core demographics |
| Disease_disorder | Condition | Clinical status: active, Verification: confirmed |
| Diagnosis | Condition | Same as Disease_disorder |
| Medication | MedicationStatement | Status: active |
| Dosage | MedicationStatement.dosage | Linked to medication |
| Procedure | Procedure | Status: completed |
| Lab_Tests | Observation | Status: final, with valueQuantity |
| Admission | Encounter | Period, reasonCode, serviceType |
| Discharge | Encounter | Period.end, hospitalization.dischargeDisposition |

##  Testing

Run the test suite:
```bash
python -m pytest tests/test_document_mapper.py -v
```

Or use the quick test:
```bash
python test_quick.py
```

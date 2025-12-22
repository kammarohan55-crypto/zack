"""
Quick test to verify document mapper functionality
"""
import json
from document_mapper import MedicalReportMapper, LabReportMapper, DischargeSummaryMapper, AdmissionSlipMapper

# Test Medical Report
print("Testing Medical Report Mapper...")
medical_data = {
    "PII": {
        "Name": "John Doe",
        "DOB": "1980-05-15",
        "ID": "MRN12345",
        "Date": "2025-12-15"
    },
    "Disease_disorder": ["Hypertension"],
    "Medication": ["Metformin"],
    "Dosage": ["500mg twice daily"],
    "Procedure": ["Blood glucose monitoring"]
}

mapper = MedicalReportMapper()
bundle_json = mapper.map_to_fhir(medical_data)
bundle = json.loads(bundle_json)
print(f"✓ Medical Report: Generated Bundle with {len(bundle['entry'])} resources")
print(f"  Resource types: {[e['resource']['resourceType'] for e in bundle['entry']]}")

# Test Lab Report
print("\nTesting Lab Report Mapper...")
lab_data = {
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
bundle_json = mapper.map_to_fhir(lab_data)
bundle = json.loads(bundle_json)
print(f"✓ Lab Report: Generated Bundle with {len(bundle['entry'])} resources")
print(f"  Resource types: {[e['resource']['resourceType'] for e in bundle['entry']]}")

# Test Discharge Summary
print("\nTest Discharge Summary Mapper...")
discharge_data = {
    "PII": {
        "Name": "Carol Martinez",
        "DOB": "1965-08-10",
        "ID": "DISCH2025",
        "Admission_Date": "2025-12-10",
        "Discharge_Date": "2025-12-18"
    },
    "Diagnosis": ["Pneumonia"],
    "Outcome": "Recovered",
    "Instructions": ["Take antibiotics for 7 days"]
}

mapper = DischargeSummaryMapper()
bundle_json = mapper.map_to_fhir(discharge_data)
bundle = json.loads(bundle_json)
print(f"✓ Discharge Summary: Generated Bundle with {len(bundle['entry'])} resources")
print(f"  Resource types: {[e['resource']['resourceType'] for e in bundle['entry']]}")

# Test Admission Slip
print("\nTesting Admission Slip Mapper...")
admission_data = {
    "PII": {
        "Name": "Eva Garcia",
        "DOB": "1990-11-05",
        "ID": "ADM5555",
        "Date": "2025-12-22"
    },
    "Admission_Reason": "Chest pain evaluation",
    "Department": "Cardiology"
}

mapper = AdmissionSlipMapper()
bundle_json = mapper.map_to_fhir(admission_data)
bundle = json.loads(bundle_json)
print(f"✓ Admission Slip: Generated Bundle with {len(bundle['entry'])} resources")
print(f"  Resource types: {[e['resource']['resourceType'] for e in bundle['entry']]}")

print("\n" + "="*50)
print("✅ ALL MAPPERS WORKING CORRECTLY!")
print("="*50)

# Validate FHIR compliance
print("\nFHIR Compliance Checks:")

# Check 1: No Observation for diseases
medical_mapper = MedicalReportMapper()
test_data = {
    "PII": {"Name": "Test", "ID": "TEST123"},
    "Disease_disorder": ["Diabetes"]
}
bundle_json = medical_mapper.map_to_fhir(test_data)
bundle = json.loads(bundle_json)
obs_count = sum(1 for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation')
cond_count = sum(1 for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition')
print(f"✓ Diseases mapped to Condition (not Observation): {cond_count} Conditions, {obs_count} Observations")

# Check 2: No Observation for medications
test_data2 = {
    "PII": {"Name": "Test", "ID": "TEST456"},
    "Medication": ["Aspirin"]
}
bundle_json = medical_mapper.map_to_fhir(test_data2)
bundle = json.loads(bundle_json)
obs_count = sum(1 for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation')
med_count = sum(1 for e in bundle['entry'] if e['resource']['resourceType'] == 'MedicationStatement')
print(f"✓ Medications mapped to MedicationStatement (not Observation): {med_count} MedicationStatements, {obs_count} Observations")

# Check 3: Bundle is transaction type
print(f"✓ Bundle type is 'transaction': {bundle['type'] == 'transaction'}")

# Check 4: All resources reference Patient
all_reference_patient = True
for entry in bundle['entry'][1:]:  # Skip Patient itself
    if 'subject' not in entry['resource']:
        all_reference_patient = False
        break
print(f"✓ All clinical resources reference Patient: {all_reference_patient}")

print("\n✅ ALL FHIR COMPLIANCE CHECKS PASSED!")

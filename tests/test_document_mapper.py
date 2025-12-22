"""
Test suite for FHIR R4 Document Mapper

Tests all four document types:
- Medical Report
- Lab Report
- Discharge Summary
- Admission Slip
"""

import pytest
import json
from document_mapper import (
    MedicalReportMapper,
    LabReportMapper,
    DischargeSummaryMapper,
    AdmissionSlipMapper,
    get_document_mapper
)


class TestMedicalReportMapper:
    """Test Medical Report to FHIR mapping."""
    
    def test_complete_medical_report(self):
        """Test mapping with all fields present."""
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
            "Procedure": ["Blood glucose monitoring", "Blood pressure check"]
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Verify Bundle structure
        assert bundle['resourceType'] == 'Bundle'
        assert bundle['type'] == 'transaction'
        assert len(bundle['entry']) == 7  # 1 Patient + 2 Conditions + 2 MedicationStatements + 2 Procedures
        
        # Verify Patient resource
        patient = bundle['entry'][0]['resource']
        assert patient['resourceType'] == 'Patient'
        assert patient['id'] == 'MRN12345'
        assert patient['name'][0]['given'] == ['John']
        assert patient['name'][0]['family'] == 'Doe'
        assert patient['birthDate'] == '1980-05-15'
        
        # Verify Condition resources (diseases)
        conditions = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition']
        assert len(conditions) == 2
        assert conditions[0]['code']['text'] in ['Hypertension', 'Type 2 Diabetes']
        assert conditions[0]['subject']['reference'] == 'Patient/MRN12345'
        assert conditions[0]['clinicalStatus']['coding'][0]['code'] == 'active'
        assert conditions[0]['verificationStatus']['coding'][0]['code'] == 'confirmed'
        
        # Verify MedicationStatement resources
        med_statements = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'MedicationStatement']
        assert len(med_statements) == 2
        assert med_statements[0]['medicationCodeableConcept']['text'] in ['Metformin', 'Lisinopril']
        assert med_statements[0]['subject']['reference'] == 'Patient/MRN12345'
        assert med_statements[0]['status'] == 'active'
        assert 'dosage' in med_statements[0]
        
        # Verify Procedure resources
        procedures = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Procedure']
        assert len(procedures) == 2
        assert procedures[0]['subject']['reference'] == 'Patient/MRN12345'
        assert procedures[0]['status'] == 'completed'
    
    def test_minimal_medical_report(self):
        """Test mapping with minimal required fields."""
        data = {
            "PII": {
                "Name": "Jane Smith",
                "ID": "MRN67890"
            },
            "Disease_disorder": ["Asthma"]
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        assert bundle['resourceType'] == 'Bundle'
        assert len(bundle['entry']) == 2  # Patient + 1 Condition


class TestLabReportMapper:
    """Test Lab Report to FHIR mapping."""
    
    def test_complete_lab_report(self):
        """Test lab report with multiple tests."""
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
                },
                {
                    "Name": "White Blood Cell Count",
                    "Value": "7.2",
                    "Unit": "10^9/L",
                    "Reference_Range": "4.0-11.0 10^9/L"
                },
                {
                    "Name": "Blood Glucose",
                    "Value": "95",
                    "Unit": "mg/dL",
                    "Reference_Range": "70-100 mg/dL"
                }
            ]
        }
        
        mapper = LabReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Verify Bundle structure
        assert bundle['resourceType'] == 'Bundle'
        assert bundle['type'] == 'transaction'
        assert len(bundle['entry']) == 4  # 1 Patient + 3 Observations
        
        # Verify Patient
        patient = bundle['entry'][0]['resource']
        assert patient['resourceType'] == 'Patient'
        
        # Verify Observation resources
        observations = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation']
        assert len(observations) == 3
        
        # Check first observation
        obs = observations[0]
        assert obs['code']['text'] in ['Hemoglobin', 'White Blood Cell Count', 'Blood Glucose']
        assert obs['status'] == 'final'
        assert obs['subject']['reference'] == f"Patient/{patient['id']}"
        assert 'valueQuantity' in obs
        assert obs['valueQuantity']['value'] > 0
        assert 'unit' in obs['valueQuantity']
        assert len(obs['referenceRange']) == 1
    
    def test_lab_report_without_units(self):
        """Test lab report where some tests don't have units."""
        data = {
            "PII": {
                "Name": "Bob Williams",
                "ID": "LAB11111"
            },
            "Lab_Tests": [
                {
                    "Name": "pH",
                    "Value": "7.4"
                }
            ]
        }
        
        mapper = LabReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        observations = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation']
        assert len(observations) == 1
        assert observations[0]['valueQuantity']['value'] == 7.4


class TestDischargeSummaryMapper:
    """Test Discharge Summary to FHIR mapping."""
    
    def test_complete_discharge_summary(self):
        """Test discharge summary with all fields."""
        data = {
            "PII": {
                "Name": "Carol Martinez",
                "DOB": "1965-08-10",
                "ID": "DISCH2025",
                "Admission_Date": "2025-12-10",
                "Discharge_Date": "2025-12-18"
            },
            "Diagnosis": ["Pneumonia", "Dehydration"],
            "Outcome": "Recovered",
            "Instructions": [
                "Take antibiotics for 7 days",
                "Drink plenty of fluids",
                "Follow up in 2 weeks"
            ]
        }
        
        mapper = DischargeSummaryMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Verify Bundle structure
        assert bundle['resourceType'] == 'Bundle'
        assert len(bundle['entry']) == 4  # 1 Patient + 2 Conditions + 1 Encounter
        
        # Verify Conditions
        conditions = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition']
        assert len(conditions) == 2
        assert conditions[0]['code']['text'] in ['Pneumonia', 'Dehydration']
        
        # Verify Encounter
        encounters = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Encounter']
        assert len(encounters) == 1
        encounter = encounters[0]
        assert encounter['status'] == 'finished'
        assert encounter['period']['start'] == '2025-12-10'
        assert encounter['period']['end'] == '2025-12-18'
        assert 'Outcome: Recovered' in encounter['hospitalization']['dischargeDisposition']['text']
        assert 'Instructions:' in encounter['hospitalization']['dischargeDisposition']['text']
    
    def test_discharge_summary_minimal(self):
        """Test discharge summary with minimal data."""
        data = {
            "PII": {
                "Name": "David Lee",
                "ID": "DISCH9999",
                "Discharge_Date": "2025-12-20"
            },
            "Diagnosis": ["Appendicitis"]
        }
        
        mapper = DischargeSummaryMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        encounters = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Encounter']
        assert len(encounters) == 1


class TestAdmissionSlipMapper:
    """Test Admission Slip to FHIR mapping."""
    
    def test_complete_admission_slip(self):
        """Test admission slip with all fields."""
        data = {
            "PII": {
                "Name": "Eva Garcia",
                "DOB": "1990-11-05",
                "ID": "ADM5555",
                "Date": "2025-12-22"
            },
            "Admission_Reason": "Chest pain evaluation",
            "Doctor": "Dr. Sarah Johnson",
            "Department": "Cardiology"
        }
        
        mapper = AdmissionSlipMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Verify Bundle structure
        assert bundle['resourceType'] == 'Bundle'
        assert len(bundle['entry']) == 2  # 1 Patient + 1 Encounter
        
        # Verify Encounter
        encounters = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Encounter']
        assert len(encounters) == 1
        encounter = encounters[0]
        assert encounter['status'] == 'finished'
        assert encounter['period']['start'] == '2025-12-22'
        assert encounter['reasonCode'][0]['text'] == 'Chest pain evaluation'
        assert encounter['serviceType']['text'] == 'Cardiology'
    
    def test_admission_slip_minimal(self):
        """Test admission slip with minimal data."""
        data = {
            "PII": {
                "Name": "Frank Wilson",
                "ID": "ADM7777"
            },
            "Admission_Reason": "Emergency admission"
        }
        
        mapper = AdmissionSlipMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        assert bundle['resourceType'] == 'Bundle'
        assert len(bundle['entry']) == 2


class TestDocumentMapperFactory:
    """Test the document mapper factory function."""
    
    def test_get_medical_report_mapper(self):
        """Test getting Medical Report mapper."""
        mapper = get_document_mapper("Medical Report")
        assert isinstance(mapper, MedicalReportMapper)
    
    def test_get_lab_report_mapper(self):
        """Test getting Lab Report mapper."""
        mapper = get_document_mapper("Lab Report")
        assert isinstance(mapper, LabReportMapper)
    
    def test_get_discharge_summary_mapper(self):
        """Test getting Discharge Summary mapper."""
        mapper = get_document_mapper("Discharge Summary")
        assert isinstance(mapper, DischargeSummaryMapper)
    
    def test_get_admission_slip_mapper(self):
        """Test getting Admission Slip mapper."""
        mapper = get_document_mapper("Admission Slip")
        assert isinstance(mapper, AdmissionSlipMapper)
    
    def test_invalid_document_type(self):
        """Test error handling for invalid document type."""
        with pytest.raises(ValueError, match="Unsupported document type"):
            get_document_mapper("Invalid Type")


class TestFHIRCompliance:
    """Test FHIR R4 compliance rules."""
    
    def test_no_observation_for_diseases(self):
        """Ensure diseases are mapped to Condition, NOT Observation."""
        data = {
            "PII": {"Name": "Test Patient", "ID": "TEST123"},
            "Disease_disorder": ["Diabetes"]
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Should NOT have any Observation resources
        observations = [e for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation']
        assert len(observations) == 0
        
        # Should have Condition resource
        conditions = [e for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition']
        assert len(conditions) == 1
    
    def test_no_observation_for_medications(self):
        """Ensure medications are mapped to MedicationStatement, NOT Observation."""
        data = {
            "PII": {"Name": "Test Patient", "ID": "TEST456"},
            "Medication": ["Aspirin"]
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        # Should NOT have any Observation resources
        observations = [e for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation']
        assert len(observations) == 0
        
        # Should have MedicationStatement resource
        med_statements = [e for e in bundle['entry'] if e['resource']['resourceType'] == 'MedicationStatement']
        assert len(med_statements) == 1
    
    def test_all_resources_reference_patient(self):
        """Ensure all clinical resources reference the Patient."""
        data = {
            "PII": {"Name": "Test Patient", "ID": "TEST789", "DOB": "1990-01-01"},
            "Disease_disorder": ["Condition1"],
            "Medication": ["Med1"],
            "Procedure": ["Proc1"]
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        patient_id = bundle['entry'][0]['resource']['id']
        
        # Check all non-Patient resources reference the Patient
        for entry in bundle['entry'][1:]:  # Skip Patient itself
            resource = entry['resource']
            assert 'subject' in resource
            assert resource['subject']['reference'] == f'Patient/{patient_id}'
    
    def test_transaction_bundle_structure(self):
        """Ensure Bundle is of type 'transaction' with correct structure."""
        data = {
            "PII": {"Name": "Test Patient", "ID": "BUNDLE123"}
        }
        
        mapper = MedicalReportMapper()
        bundle_json = mapper.map_to_fhir(data)
        bundle = json.loads(bundle_json)
        
        assert bundle['resourceType'] == 'Bundle'
        assert bundle['type'] == 'transaction'
        assert 'entry' in bundle
        
        # Verify each entry has request
        for entry in bundle['entry']:
            assert 'request' in entry
            assert entry['request']['method'] == 'POST'
            assert 'url' in entry['request']

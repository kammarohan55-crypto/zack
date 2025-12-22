"""
FHIR R4 Clinical Document Mapper

Maps structured JSON from medical document extraction to FHIR R4 Bundles.
Supports: Medical Reports, Lab Reports, Discharge Summaries, Admission Slips.

CRITICAL RULES:
- Follow FHIR R4 specification strictly
- NO fake/placeholder data
- Use correct resource types (Condition for diseases, NOT Observation)
- All clinical resources MUST reference Patient
- Output transaction Bundles only
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from fhir.resources.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.patient import Patient
from fhir.resources.humanname import HumanName
from fhir.resources.condition import Condition
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.dosage import Dosage
from fhir.resources.procedure import Procedure
from fhir.resources.observation import Observation, ObservationReferenceRange
from fhir.resources.quantity import Quantity
from fhir.resources.encounter import Encounter

logger = logging.getLogger(__name__)


class DocumentMapper:
    """Base class for FHIR document mapping with common resource builders."""
    
    def __init__(self):
        self.patient_id = None
        self.entries = []
    
    def map_to_fhir(self, data: Dict[str, Any]) -> str:
        """
        Main entry point for mapping. Must be implemented by subclasses.
        Returns: JSON string of FHIR Bundle
        """
        raise NotImplementedError("Subclasses must implement map_to_fhir")
    
    def _build_patient(self, pii: Dict[str, Any]) -> Patient:
        """
        Build FHIR Patient resource from PII data.
        
        Expected PII fields:
        - Name: patient name (string)
        - DOB: date of birth (ISO-8601)
        - ID: patient identifier (string)
        """
        patient = Patient.model_construct()
        
        # Set patient ID
        patient_id = pii.get('ID') or pii.get('id')
        if patient_id:
            self.patient_id = str(patient_id)
            patient.id = self.patient_id
        else:
            # Generate UUID if no ID provided
            self.patient_id = str(uuid.uuid4())
            patient.id = self.patient_id
        
        # Parse name
        name_str = pii.get('Name') or pii.get('name')
        if name_str:
            name = HumanName.model_construct()
            name_parts = name_str.strip().split()
            if len(name_parts) >= 2:
                name.given = name_parts[:-1]
                name.family = name_parts[-1]
            elif len(name_parts) == 1:
                name.family = name_parts[0]
            else:
                name.text = name_str
            patient.name = [name]
        
        # Set birth date (ISO-8601 format)
        dob = pii.get('DOB') or pii.get('dob')
        if dob:
            patient.birthDate = self._normalize_date(dob)
        
        return patient
    
    def _build_condition(self, text: str, date: Optional[str] = None) -> Condition:
        """
        Build FHIR Condition resource for disease/diagnosis.
        
        Args:
            text: Disease or diagnosis name
            date: Optional recorded date
        """
        condition = Condition.model_construct()
        condition.id = str(uuid.uuid4())
        
        # Reference patient
        condition.subject = {"reference": f"Patient/{self.patient_id}"}
        
        # Set condition text (no standard coding provided)
        condition.code = CodeableConcept.model_construct()
        condition.code.text = text
        
        # Clinical status: active (assuming current condition)
        condition.clinicalStatus = CodeableConcept.model_construct()
        condition.clinicalStatus.coding = [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active"
        }]
        
        # Verification status: confirmed
        condition.verificationStatus = CodeableConcept.model_construct()
        condition.verificationStatus.coding = [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            "code": "confirmed"
        }]
        
        # Set recorded date if available
        if date:
            condition.recordedDate = self._normalize_date(date)
        
        return condition
    
    def _build_medication_statement(self, medication: str, dosage_text: Optional[str] = None) -> MedicationStatement:
        """
        Build FHIR MedicationStatement resource.
        
        Args:
            medication: Medication name
            dosage_text: Optional dosage instructions
        """
        # Prepare medication concept
        med_concept = CodeableConcept.model_construct(text=medication)
        
        # Prepare dosage if provided
        dosage_list = None
        if dosage_text:
            dosage_list = [Dosage.model_construct(text=dosage_text)]
        
        # Build medication statement with all kwargs
        med_statement = MedicationStatement.model_construct(
            id=str(uuid.uuid4()),
            subject={"reference": f"Patient/{self.patient_id}"},
            medicationCodeableConcept=med_concept,
            status="active",
            dosage=dosage_list
        )
        
        return med_statement
    
    def _build_procedure(self, procedure_name: str, date: Optional[str] = None) -> Procedure:
        """
        Build FHIR Procedure resource.
        
        Args:
            procedure_name: Name of the procedure
            date: Optional procedure date
        """
        procedure = Procedure.model_construct()
        procedure.id = str(uuid.uuid4())
        
        # Reference patient
        procedure.subject = {"reference": f"Patient/{self.patient_id}"}
        
        # Set procedure code
        procedure.code = CodeableConcept.model_construct()
        procedure.code.text = procedure_name
        
        # Status: completed (assuming past procedure)
        procedure.status = "completed"
        
        # Set performed date if available
        if date:
            procedure.performedDateTime = self._normalize_date(date)
        
        return procedure
    
    def _build_observation(self, test_name: str, value: Any, unit: Optional[str] = None,
                          reference_range: Optional[str] = None, date: Optional[str] = None) -> Observation:
        """
        Build FHIR Observation resource for lab tests ONLY.
        
        Args:
            test_name: Lab test name
            value: Test value (numeric or string)
            unit: Unit of measurement
            reference_range: Reference range text
            date: Test date
        """
        observation = Observation.model_construct()
        observation.id = str(uuid.uuid4())
        
        # Reference patient
        observation.subject = {"reference": f"Patient/{self.patient_id}"}
        
        # Set observation code (lab test name)
        observation.code = CodeableConcept.model_construct()
        observation.code.text = test_name
        
        # Status: final
        observation.status = "final"
        
        # Set value as quantity if numeric
        if value is not None:
            try:
                numeric_value = float(value)
                observation.valueQuantity = Quantity.model_construct()
                observation.valueQuantity.value = numeric_value
                if unit:
                    observation.valueQuantity.unit = unit
            except (ValueError, TypeError):
                # If not numeric, use valueString
                observation.valueString = str(value)
        
        # Set reference range if provided
        if reference_range:
            ref_range = ObservationReferenceRange.model_construct()
            ref_range.text = reference_range
            observation.referenceRange = [ref_range]
        
        # Set effective date
        if date:
            observation.effectiveDateTime = self._normalize_date(date)
        else:
            observation.effectiveDateTime = datetime.utcnow().isoformat()
        
        return observation
    
    def _build_encounter(self, admission_date: Optional[str] = None, discharge_date: Optional[str] = None,
                        admission_reason: Optional[str] = None, department: Optional[str] = None,
                        outcome: Optional[str] = None, instructions: Optional[List[str]] = None) -> Encounter:
        """
        Build FHIR Encounter resource for admission/discharge.
        
        Args:
            admission_date: Admission date
            discharge_date: Discharge date
            admission_reason: Reason for admission
            department: Department/service type
            outcome: Discharge outcome
            instructions: Discharge instructions
        """
        encounter = Encounter.model_construct()
        encounter.id = str(uuid.uuid4())
        
        # Reference patient
        encounter.subject = {"reference": f"Patient/{self.patient_id}"}
        
        # Status: finished (assuming completed encounter)
        encounter.status = "finished"
        
        # Class: inpatient
        encounter.class_fhir = {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP",
            "display": "inpatient encounter"
        }
        
        # Set period (admission to discharge) using dict structure
        if admission_date or discharge_date:
            period_dict = {}
            if admission_date:
                period_dict["start"] = self._normalize_date(admission_date)
            if discharge_date:
                period_dict["end"] = self._normalize_date(discharge_date)
            encounter.period = period_dict
        
        # Set admission reason
        if admission_reason:
            encounter.reasonCode = [CodeableConcept.model_construct()]
            encounter.reasonCode[0].text = admission_reason
        
        # Set service type (department)
        if department:
            encounter.serviceType = CodeableConcept.model_construct()
            encounter.serviceType.text = department
        
        # Set hospitalization details using dict structure
        if outcome or instructions:
            # Discharge disposition (outcome + instructions)
            disposition_text = []
            if outcome:
                disposition_text.append(f"Outcome: {outcome}")
            if instructions:
                disposition_text.append("Instructions: " + "; ".join(instructions))
            
            if disposition_text:
                discharge_disp = CodeableConcept.model_construct()
                discharge_disp.text = " | ".join(disposition_text)
                encounter.hospitalization = {
                    "dischargeDisposition": discharge_disp
                }
        
        return encounter
    
    def _build_bundle(self, resources: List[Any]) -> Bundle:
        """
        Build FHIR transaction Bundle from resources.
        
        Args:
            resources: List of FHIR resources
        """
        bundle = Bundle.model_construct()
        bundle.type = "transaction"
        
        bundle.entry = []
        for resource in resources:
            entry = BundleEntry.model_construct()
            entry.resource = resource
            # Use dict for request instead of BundleEntryRequest.model_construct()
            # Get resource type from class name
            entry.request = {'method': 'POST', 'url': type(resource).__name__}
            bundle.entry.append(entry)
        
        return bundle
    
    def _normalize_date(self, date_str: str) -> str:
        """
        Normalize date to ISO-8601 format.
        Handles various input formats.
        """
        if not date_str:
            return None
        
        # Already ISO-8601 format
        if 'T' in date_str or len(date_str) == 10:
            return date_str
        
        # Try to parse and convert common formats
        try:
            # Try common formats
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Could not parse date {date_str}: {e}")
        
        # Return as-is if parsing fails
        return date_str


class MedicalReportMapper(DocumentMapper):
    """Maps Medical Report JSON to FHIR Bundle."""
    
    def map_to_fhir(self, data: Dict[str, Any]) -> str:
        """
        Map Medical Report to FHIR Bundle.
        
        Expected structure:
        {
            "PII": {"Name", "DOB", "ID", "Date"},
            "Disease_disorder": [...],
            "Medication": [...],
            "Dosage": [...],
            "Procedure": [...]
        }
        """
        resources = []
        
        # 1. Create Patient resource
        pii = data.get('PII', {})
        patient = self._build_patient(pii)
        resources.append(patient)
        
        report_date = pii.get('Date')
        
        # 2. Create Condition resources for diseases
        diseases = data.get('Disease_disorder', [])
        if diseases:
            for disease in diseases:
                if disease:  # Skip empty strings
                    condition = self._build_condition(disease, report_date)
                    resources.append(condition)
        
        # 3. Create MedicationStatement resources
        medications = data.get('Medication', [])
        dosages = data.get('Dosage', [])
        
        # Ensure dosages list is same length as medications
        while len(dosages) < len(medications):
            dosages.append(None)
        
        for med, dose in zip(medications, dosages):
            if med:  # Skip empty strings
                med_statement = self._build_medication_statement(med, dose)
                resources.append(med_statement)
        
        # 4. Create Procedure resources
        procedures = data.get('Procedure', [])
        if procedures:
            for proc in procedures:
                if proc:  # Skip empty strings
                    procedure = self._build_procedure(proc, report_date)
                    resources.append(procedure)
        
        # 5. Build transaction Bundle
        bundle = self._build_bundle(resources)
        
        return bundle.model_dump_json(exclude_none=True)


class LabReportMapper(DocumentMapper):
    """Maps Lab Report JSON to FHIR Bundle."""
    
    def map_to_fhir(self, data: Dict[str, Any]) -> str:
        """
        Map Lab Report to FHIR Bundle.
        
        Expected structure:
        {
            "PII": {"Name", "DOB", "ID", "Date"},
            "Lab_Tests": [
                {"Name", "Value", "Unit", "Reference_Range"}
            ]
        }
        """
        resources = []
        
        # 1. Create Patient resource
        pii = data.get('PII', {})
        patient = self._build_patient(pii)
        resources.append(patient)
        
        test_date = pii.get('Date')
        
        # 2. Create Observation resources for each lab test
        lab_tests = data.get('Lab_Tests', [])
        if lab_tests:
            for test in lab_tests:
                if isinstance(test, dict):
                    test_name = test.get('Name')
                    if test_name:  # Only create if test name exists
                        observation = self._build_observation(
                            test_name=test_name,
                            value=test.get('Value'),
                            unit=test.get('Unit'),
                            reference_range=test.get('Reference_Range'),
                            date=test_date
                        )
                        resources.append(observation)
        
        # 3. Build transaction Bundle
        bundle = self._build_bundle(resources)
        
        return bundle.json()


class DischargeSummaryMapper(DocumentMapper):
    """Maps Discharge Summary JSON to FHIR Bundle."""
    
    def map_to_fhir(self, data: Dict[str, Any]) -> str:
        """
        Map Discharge Summary to FHIR Bundle.
        
        Expected structure:
        {
            "PII": {"Name", "DOB", "ID", "Admission_Date", "Discharge_Date"},
            "Diagnosis": [...],
            "Outcome": "...",
            "Instructions": [...]
        }
        """
        resources = []
        
        # 1. Create Patient resource
        pii = data.get('PII', {})
        patient = self._build_patient(pii)
        resources.append(patient)
        
        # 2. Create Condition resources for diagnoses
        diagnoses = data.get('Diagnosis', [])
        discharge_date = pii.get('Discharge_Date')
        
        if diagnoses:
            for diagnosis in diagnoses:
                if diagnosis:  # Skip empty strings
                    condition = self._build_condition(diagnosis, discharge_date)
                    resources.append(condition)
        
        # 3. Create Encounter resource
        admission_date = pii.get('Admission_Date')
        outcome = data.get('Outcome')
        instructions = data.get('Instructions', [])
        
        encounter = self._build_encounter(
            admission_date=admission_date,
            discharge_date=discharge_date,
            outcome=outcome,
            instructions=instructions if instructions else None
        )
        resources.append(encounter)
        
        # 4. Build transaction Bundle
        bundle = self._build_bundle(resources)
        
        return bundle.model_dump_json(exclude_none=True)


class AdmissionSlipMapper(DocumentMapper):
    """Maps Admission Slip JSON to FHIR Bundle."""
    
    def map_to_fhir(self, data: Dict[str, Any]) -> str:
        """
        Map Admission Slip to FHIR Bundle.
        
        Expected structure:
        {
            "PII": {"Name", "DOB", "ID", "Date"},
            "Admission_Reason": "...",
            "Doctor": "...",
            "Department": "..."
        }
        """
        resources = []
        
        # 1. Create Patient resource
        pii = data.get('PII', {})
        patient = self._build_patient(pii)
        resources.append(patient)
        
        # 2. Create Encounter resource
        admission_date = pii.get('Date')
        admission_reason = data.get('Admission_Reason')
        department = data.get('Department')
        
        encounter = self._build_encounter(
            admission_date=admission_date,
            admission_reason=admission_reason,
            department=department
        )
        resources.append(encounter)
        
        # Note: Doctor information could be added as Encounter.participant
        # but would require creating Practitioner resource
        # Omitting for now to avoid placeholder data
        
        # 3. Build transaction Bundle
        bundle = self._build_bundle(resources)
        
        return bundle.json()


# Factory function for getting the right mapper
def get_document_mapper(document_type: str) -> DocumentMapper:
    """
    Factory function to get appropriate mapper for document type.
    
    Args:
        document_type: One of "Medical Report", "Lab Report", 
                      "Discharge Summary", "Admission Slip"
    
    Returns:
        DocumentMapper instance
    
    Raises:
        ValueError: If document type is not supported
    """
    mappers = {
        "Medical Report": MedicalReportMapper,
        "Lab Report": LabReportMapper,
        "Discharge Summary": DischargeSummaryMapper,
        "Admission Slip": AdmissionSlipMapper
    }
    
    mapper_class = mappers.get(document_type)
    if not mapper_class:
        raise ValueError(
            f"Unsupported document type: {document_type}. "
            f"Supported types: {', '.join(mappers.keys())}"
        )
    
    return mapper_class()

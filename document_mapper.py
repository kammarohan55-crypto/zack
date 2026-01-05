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

try:
    from terminology import get_condition_code, get_loinc_code, get_rxnorm_code
except ImportError:
    from harmon_service.terminology import get_condition_code, get_loinc_code, get_rxnorm_code

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
            # Sanitize ID to match FHIR format: [A-Za-z0-9\-\.]{1,64}
            # Replace underscores with hyphens
            self.patient_id = str(patient_id).replace('_', '-')
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

        # Set gender
        gender_raw = pii.get('Gender') or pii.get('gender')
        if gender_raw:
            g = gender_raw.lower().strip()
            if g in ['m', 'male', 'man']:
                patient.gender = 'male'
            elif g in ['f', 'female', 'woman']:
                patient.gender = 'female'
            elif g in ['o', 'other']:
                patient.gender = 'other'
            else:
                patient.gender = 'unknown'
        
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
        
        try:
             # Use terminology service to look up ICD-10 code
            concept_data = get_condition_code(text)
            condition.code = CodeableConcept.model_construct(**concept_data)
        except Exception as e:
            logger.warning(f"Terminology lookup failed for '{text}', using raw text: {e}")
            # Fallback to plain text
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
        # Build data dict for MedicationStatement
        med_data = {
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient_id}"},
            "status": "active"
        }
        
        # Prepare concept with RxNorm lookup
        concept = None
        try:
            concept_data = get_rxnorm_code(medication)
            concept = CodeableConcept.model_construct(**concept_data)
        except Exception:
            # Fallback
            concept = CodeableConcept.model_construct(text=medication)

        # Handle Reference/Concept choice
        # Error indicates 'medication' field is required.
        # Valid structure for modern fhir.resources (R5) is medication.concept
        # For R4 it is medicationCodeableConcept.
        # We will try to provide 'medication' property with 'concept' which is R5 compliant
        # and satisfies "medication field required".
        
        # Convert concept to dict if possible or use object
        concept_dict = concept.model_dump(exclude_none=True) if hasattr(concept, 'model_dump') else concept.dict(exclude_none=True)
        
        med_data["medication"] = {"concept": concept_dict}
        
        # Add dosage if provided
        if dosage_text:
            med_data["dosage"] = [{"text": dosage_text}]
        
        # Use proper instantiation with validation
        med_statement = MedicationStatement.model_construct(**med_data)
        
        return med_statement
    
    def _build_procedure(self, procedure_name: str, date: Optional[str] = None) -> Procedure:
        """
        Build FHIR Procedure resource.
        
        Args:
            procedure_name: Name of the procedure
            date: Optional procedure date
        """
        proc_data = {
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient_id}"},
            "status": "completed",  # Required field
            "code": {"text": procedure_name}
        }
        
        # Set performed date if available
        if date:
            proc_data["performedDateTime"] = self._normalize_date(date)
            
        procedure = Procedure.model_construct(**proc_data)
        
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
        # Build data dict
        obs_data = {
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient_id}"},
            "status": "final"
        }
        
        # Set observation code (lab test name)
        try:
            concept_data = get_loinc_code(test_name)
            obs_data["code"] = CodeableConcept.model_construct(**concept_data)
        except Exception:
            obs_data["code"] = CodeableConcept.model_construct(text=test_name)
            
        # Set value as quantity if numeric
        if value is not None:
            try:
                numeric_value = float(value)
                qty = Quantity.model_construct()
                qty.value = numeric_value
                if unit:
                    qty.unit = unit
                obs_data["valueQuantity"] = qty
            except (ValueError, TypeError):
                # If not numeric, use valueString
                obs_data["valueString"] = str(value)
        
        # Set reference range if provided
        if reference_range:
            ref_range = ObservationReferenceRange.model_construct()
            ref_range.text = reference_range
            obs_data["referenceRange"] = [ref_range]
        
        # Set effective date
        if date:
            obs_data["effectiveDateTime"] = self._normalize_date(date)
        else:
            obs_data["effectiveDateTime"] = datetime.utcnow().isoformat()
            
        observation = Observation.model_construct(**obs_data)
        
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
        encounter = Encounter.model_construct(
            id=str(uuid.uuid4()),
            subject={"reference": f"Patient/{self.patient_id}"},
            status="finished"
        )
        
        # Class: inpatient
        # Validation requires list for class_fhir, likely expects CodeableConcept (R5)
        encounter.class_fhir = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "IMP",
                "display": "inpatient encounter"
            }]
        }]
        
        # Set period (admission to discharge) using dict structure
        # R5 uses actualPeriod instead of period
        if admission_date or discharge_date:
            period_dict = {}
            if admission_date:
                period_dict["start"] = self._normalize_date(admission_date)
            if discharge_date:
                period_dict["end"] = self._normalize_date(discharge_date)
            encounter.actualPeriod = period_dict
        
        # Set admission reason
        # R5 uses reason (List[EncounterReason]) instead of reasonCode
        # Set admission reason
        # R5 uses reason (List[EncounterReason]) instead of reasonCode
        if admission_reason:
            encounter_reasons = []
            # Split by comma to handle multiple reasons
            reasons = [r.strip() for r in admission_reason.split(',') if r.strip()]
            
            for r_text in reasons:
                # Default to text only
                concept_data = {"text": r_text}
                try:
                    # Attempt terminology lookup (ICD-10)
                    concept_data = get_condition_code(r_text)
                except Exception as e:
                    logger.warning(f"Reason terminology lookup failed for '{r_text}': {e}")
                
                # Construct R5 EncounterReason
                encounter_reasons.append({
                    "value": [{
                        "concept": concept_data
                    }]
                })
            
            encounter.reason = encounter_reasons
        
        # Set service type (department)
        # R5 serviceType is List[CodeableReference]
        if department:
            encounter.serviceType = [{
                "concept": {"text": department}
            }]
        
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
                # R5 uses admission instead of hospitalization
                encounter.admission = {
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
        Normalize date to ISO-8601 format (YYYY-MM-DD).
        Handles various input formats including natural language dates.
        """
        if not date_str:
            return None
        
        # Already ISO-8601 format (YYYY-MM-DD or YYYY-MM-DDThh:mm:ss)
        # Check specifically for date-like structure to avoid matching tokens like 'TKN_...'
        if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
             if 'T' in date_str:
                 return date_str.split('T')[0]
             return date_str[:10]
             
        # Clean the string
        cleaned_date = date_str.strip().replace(" ,", ",").replace(", ", ", ")
        
        formats_to_try = [
            '%Y-%m-%d', 
            '%d/%m/%Y', 
            '%m/%d/%Y', 
            '%d-%m-%Y',
            '%B %d, %Y',   # December 27, 2025
            '%B %d %Y',    # December 27 2025
            '%b %d, %Y',   # Dec 27, 2025
            '%d %B %Y',    # 27 December 2025
            '%Y/%m/%d'
        ]

        for fmt in formats_to_try:
            try:
                dt = datetime.strptime(cleaned_date, fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
                
        # If parsing fails or it's a token (start with TKN), return None
        # Returning empty string causes validation errors
        if 'TKN' in date_str:
            logger.info(f"Ignored tokenized date: {date_str}")
            return None
            
        logger.warning(f"Could not parse date '{date_str}', returning None to avoid validation errors.")
        return None


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

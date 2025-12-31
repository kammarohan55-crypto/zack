import logging
import uuid
from datetime import datetime, timezone
from fhir.resources.patient import Patient
from fhir.resources.humanname import HumanName
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.observation import Observation, ObservationComponent, ObservationReferenceRange
from fhir.resources.condition import Condition
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.dosage import Dosage
from fhir.resources.procedure import Procedure
from fhir.resources.encounter import Encounter
from fhir.resources.quantity import Quantity
from terminology import get_condition_code, get_loinc_code, get_rxnorm_code

logger = logging.getLogger(__name__)

class MappingService:
    @staticmethod
    def map_legacy_to_fhir(legacy_data):
        """
        Maps legacy patient data to FHIR Bundle containing Patient and clinical resources.
        
        Expected legacy format:
        {
            "id": "123",
            "first_name": "John",
            "last_name": "Doe",
            "dob": "1980-01-01",
            "gender": "M",
            "blood_pressure": "120/80",
            
            # Disease/Diagnosis fields
            "Disease_disorder": ["Hypertension", "Diabetes"],
            "Diagnosis": ["Pneumonia"],
            
            # Medication fields
            "Medication": ["Metformin", "Lisinopril"],
            "Dosage": ["500mg twice daily", "10mg once daily"],
            
            # Procedure fields
            "Procedure": ["Blood test", "X-ray"],
            
            # Encounter fields (optional)
            "Admission_Date": "2025-01-01",
            "Discharge_Date": "2025-01-05",
            "Admission_Reason": "Chest pain"
        }
        """
        try:
            bundle_entries = []
            
            # =====================================
            # 1. Map Patient (EXISTING LOGIC)
            # =====================================
            patient = Patient.model_construct()
            patient.id = str(legacy_data.get('id', uuid.uuid4()))
            
            name = HumanName.model_construct()
            name.family = legacy_data.get('last_name')
            name.given = [legacy_data.get('first_name')]
            patient.name = [name]
            
            gender_map = {'M': 'male', 'F': 'female', 'O': 'other'}
            patient.gender = gender_map.get(legacy_data.get('gender'), 'unknown')
            
            patient.birthDate = legacy_data.get('dob')
            
            bundle_entries.append(BundleEntry(resource=patient, request={'method': 'POST', 'url': 'Patient'}))
            
            # =====================================
            # 2. Map Diseases/Diagnoses to Condition
            # =====================================
            diseases = legacy_data.get('Disease_disorder', [])
            diagnoses = legacy_data.get('Diagnosis', [])
            
            # Combine both disease and diagnosis fields
            all_conditions = []
            if isinstance(diseases, list):
                all_conditions.extend(diseases)
            elif diseases:
                all_conditions.append(diseases)
                
            if isinstance(diagnoses, list):
                all_conditions.extend(diagnoses)
            elif diagnoses:
                all_conditions.append(diagnoses)
            
            for disease in all_conditions:
                try:
                    if disease:  # Skip empty strings
                        # Use terminology service to look up ICD-10 code
                        concept_data = get_condition_code(disease)
                        
                        condition = Condition.model_construct(
                            id=str(uuid.uuid4()),
                            subject={"reference": f"Patient/{patient.id}"},
                            code=CodeableConcept.model_construct(**concept_data),
                            clinicalStatus=CodeableConcept.model_construct(
                                coding=[{
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                    "code": "active"
                                }]
                            ),
                            verificationStatus=CodeableConcept.model_construct(
                                coding=[{
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                    "code": "confirmed"
                                }]
                            )
                        )
                        bundle_entries.append(BundleEntry(resource=condition, request={'method': 'POST', 'url': 'Condition'}))
                except Exception as e_item:
                    logger.error(f"Skipping disease '{disease}' due to error: {e_item}")
                    continue
            
            # =====================================
            # 3. Map Medications to MedicationStatement (RXNORM INTEGRATED)
            # =====================================
            medications = legacy_data.get('Medication', [])
            dosages = legacy_data.get('Dosage', [])
            
            # Ensure dosages list is same length as medications
            if not isinstance(dosages, list):
                dosages = [dosages] if dosages else []
            while len(dosages) < len(medications):
                dosages.append(None)
            
            if isinstance(medications, list):
                for med, dose in zip(medications, dosages):
                    try:
                        if med:  # Skip empty strings
                            # Prepare dosage
                            dosage_list = None
                            if dose:
                                dosage_list = [Dosage.model_construct(text=dose)]
                            
                            # Use RxNorm terminology service
                            try:
                                concept_data = get_rxnorm_code(med)
                                med_code = CodeableConcept.model_construct(**concept_data)
                            except Exception:
                                # Fallback
                                med_code = CodeableConcept.model_construct(text=med)

                            med_statement = MedicationStatement.model_construct(
                                id=str(uuid.uuid4()),
                                subject={"reference": f"Patient/{patient.id}"},
                                status="active",
                                medicationCodeableConcept=med_code,
                                dosage=dosage_list
                            )
                            bundle_entries.append(BundleEntry(resource=med_statement, request={'method': 'POST', 'url': 'MedicationStatement'}))
                    except Exception as e_item:
                        logger.error(f"Skipping medication '{med}' due to error: {e_item}")
                        continue
            
            # =====================================
            # 4. Map Procedures
            # =====================================
            procedures = legacy_data.get('Procedure', [])
            
            if isinstance(procedures, list):
                for proc in procedures:
                    if proc:
                        try:
                            procedure = Procedure.model_construct(
                                id=str(uuid.uuid4()),
                                subject={"reference": f"Patient/{patient.id}"},
                                status="completed",
                                code=CodeableConcept.model_construct(text=proc)
                            )
                            bundle_entries.append(BundleEntry(resource=procedure, request={'method': 'POST', 'url': 'Procedure'}))
                        except Exception as e_item:
                            logger.error(f"Skipping procedure '{proc}' due to error: {e_item}")
                            continue
            
            # =====================================
            # 5. Map Blood Pressure to Observation (LOINC 85354-9)
            # =====================================
            bp_raw = legacy_data.get('blood_pressure')
            if bp_raw:
                try:
                    systolic, diastolic = bp_raw.split('/')
                    
                    obs_data = {
                        "id": str(uuid.uuid4()),
                        "status": "final",
                        "code": {
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "85354-9",
                                "display": "Blood pressure panel with all children optional"
                            }]
                        },
                        "subject": {"reference": f"Patient/{patient.id}"},
                        "component": [
                            {
                                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                                "valueQuantity": {"value": float(systolic), "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}
                            },
                            {
                                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                                "valueQuantity": {"value": float(diastolic), "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}
                            }
                        ],
                        "effectiveDateTime": datetime.now(timezone.utc).isoformat()
                    }
                    
                    # Construct components carefully
                    components = []
                    for comp_data in obs_data["component"]:
                        comp = ObservationComponent.model_construct(
                            code=CodeableConcept.model_construct(**comp_data["code"]),
                            valueQuantity=Quantity.model_construct(**comp_data["valueQuantity"])
                        )
                        components.append(comp)
                    
                    observation = Observation.model_construct(
                        id=obs_data["id"],
                        status=obs_data["status"],
                        code=CodeableConcept.model_construct(**obs_data["code"]),
                        subject=obs_data["subject"],
                        component=components,
                        effectiveDateTime=obs_data["effectiveDateTime"]
                    )
                    
                    bundle_entries.append(BundleEntry(resource=observation, request={'method': 'POST', 'url': 'Observation'}))
                except ValueError:
                    logger.warning(f"Invalid blood pressure format: {bp_raw}")
                except Exception as e_bp:
                    logger.error(f"Error mapping blood pressure: {e_bp}")
            
            # =====================================
            # 6. Map Lab Tests to Observation (LOINC INTEGRATED)
            # =====================================
            lab_tests = legacy_data.get('Lab_Tests', [])
            
            if isinstance(lab_tests, list):
                for test in lab_tests:
                    try:
                        if isinstance(test, dict) and test.get('Name'):
                            test_name = test.get('Name')
                            
                            # Dictionary construction for Observation
                            obs_data = {
                                "id": str(uuid.uuid4()),
                                "subject": {"reference": f"Patient/{patient.id}"},
                                "status": "final"
                            }
                            
                            # Set observation code (LOINC lookup)
                            try:
                                concept_data = get_loinc_code(test_name)
                                obs_data["code"] = CodeableConcept.model_construct(**concept_data)
                            except Exception:
                                obs_data["code"] = CodeableConcept.model_construct(text=test_name)

                            # Set effective date
                            obs_data["effectiveDateTime"] = legacy_data.get('Date') or datetime.now(timezone.utc).isoformat()
                            
                            # Add value if present
                            value = test.get('Value')
                            unit = test.get('Unit')
                            if value:
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
                            
                            # Add reference range if present
                            ref_range = test.get('Reference_Range')
                            if ref_range:
                                rr = ObservationReferenceRange.model_construct(text=ref_range)
                                obs_data["referenceRange"] = [rr]
                            
                            # Construct Observation
                            observation = Observation.model_construct(**obs_data)
                            
                            bundle_entries.append(BundleEntry(resource=observation, request={'method': 'POST', 'url': 'Observation'}))
                    except Exception as e_item:
                         logger.error(f"Skipping lab test '{test.get('Name', 'Unknown')}' due to error: {e_item}")
                         continue
            
            # =====================================
            # 7. Map Encounter (Admission/Discharge)
            # =====================================
            admission_date = legacy_data.get('Admission_Date')
            discharge_date = legacy_data.get('Discharge_Date')
            admission_reason = legacy_data.get('Admission_Reason')
            
            if admission_date or discharge_date or admission_reason:
                encounter = Encounter.model_construct(
                    id=str(uuid.uuid4()),
                    subject={"reference": f"Patient/{patient.id}"},
                    status="finished",
                    # R5 expects List[CodeableConcept] for class
                    class_fhir=[{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                            "code": "IMP",
                            "display": "inpatient encounter"
                        }]
                    }]
                )
                
                # Set period
                # R5 uses actualPeriod
                if admission_date or discharge_date:
                    period_dict = {}
                    if admission_date:
                        period_dict["start"] = admission_date
                    if discharge_date:
                        period_dict["end"] = discharge_date
                    encounter.actualPeriod = period_dict
                
                # Set admission reason
                # R5 uses reason (List[EncounterReason])
                if admission_reason:
                    encounter.reason = [{
                        "value": [{
                            "concept": {"text": admission_reason}
                        }]
                    }]
                
                bundle_entries.append(BundleEntry(resource=encounter, request={'method': 'POST', 'url': 'Encounter'}))

            # =====================================
            # Build and Return Bundle
            # =====================================
            bundle = Bundle.model_construct()
            bundle.type = 'transaction'
            bundle.entry = bundle_entries
            
            return bundle.model_dump_json()
            
        except Exception as e:
            logger.error(f"Error mapping data: {e}")
            raise ValueError(f"Mapping failed: {str(e)}")


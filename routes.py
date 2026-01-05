from flask import Blueprint, request, jsonify
from harmonization_service import HarmonizationService
from document_mapper import get_document_mapper
import logging
import json

main_bp = Blueprint('main', __name__, url_prefix='/api/v1')
logger = logging.getLogger(__name__)

@main_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'fhir-harmonization-service'}), 200

@main_bp.route('/harmonize', methods=['POST'])
def harmonize_data():
    """
    Accepts FHIR Bundle, returns Harmonized FHIR Bundle.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        harmonized_bundle = HarmonizationService.harmonize_bundle(data)
        return jsonify(json.loads(harmonized_bundle)), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error in /harmonize: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@main_bp.route('/map/document', methods=['POST'])
def map_document():
    """
    Maps clinical documents to FHIR R4 Bundles.
    
    Request body:
    {
        "document_type": "Medical Report" | "Lab Report" | "Discharge Summary" | "Admission Slip",
        "data": { ... document-specific JSON ... }
    }
    
    Returns: FHIR R4 transaction Bundle
    """
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({'error': 'No data provided'}), 400
        
        document_type = payload.get('document_type')
        if not document_type:
            return jsonify({
                'error': 'Missing document_type field',
                'supported_types': [
                    'Medical Report',
                    'Lab Report',
                    'Discharge Summary',
                    'Admission Slip'
                ]
            }), 400
        
        document_data = payload.get('data')
        if not document_data:
            return jsonify({'error': 'Missing data field'}), 400
        
        # Get appropriate mapper
        try:
            mapper = get_document_mapper(document_type)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Map to FHIR
        fhir_bundle_json = mapper.map_to_fhir(document_data)
        
        # Return as JSON
        return jsonify(json.loads(fhir_bundle_json)), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error in /map/document: {e}")
        return jsonify({'error': 'Internal server error'}), 500

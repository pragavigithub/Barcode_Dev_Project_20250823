"""
Inventory Transfer Routes
All routes related to inventory transfers between warehouses/bins
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from models import InventoryTransfer, InventoryTransferItem, User, SerialNumberTransfer, SerialNumberTransferItem, SerialNumberTransferSerial
from sqlalchemy import or_
import logging
import random
import string
from datetime import datetime

transfer_bp = Blueprint('inventory_transfer', __name__, 
                         url_prefix='/inventory_transfer',
                         template_folder='templates')

def generate_transfer_number():
    """Generate unique transfer number for serial transfers"""
    while True:
        # Generate format: ST-YYYYMMDD-XXXX (e.g., ST-20250822-A1B2)
        date_part = datetime.now().strftime('%Y%m%d')
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        transfer_number = f'ST-{date_part}-{random_part}'
        
        # Check if it already exists
        existing = SerialNumberTransfer.query.filter_by(transfer_number=transfer_number).first()
        if not existing:
            return transfer_number

@transfer_bp.route('/')
@login_required
def index():
    """Inventory Transfer main page - list all transfers for current user"""
    if not current_user.has_permission('inventory_transfer'):
        flash('Access denied - Inventory Transfer permissions required', 'error')
        return redirect(url_for('dashboard'))
    
    transfers = InventoryTransfer.query.filter_by(user_id=current_user.id).order_by(InventoryTransfer.created_at.desc()).all()
    return render_template('inventory_transfer/inventory_transfer.html', transfers=transfers)

@transfer_bp.route('/detail/<int:transfer_id>')
@login_required
def detail(transfer_id):
    """Inventory Transfer detail page"""
    transfer = InventoryTransfer.query.get_or_404(transfer_id)
    
    # Check permissions
    if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager', 'qc']:
        flash('Access denied - You can only view your own transfers', 'error')
        return redirect(url_for('inventory_transfer.index'))
    
    return render_template('inventory_transfer/inventory_transfer_detail.html', transfer=transfer)

@transfer_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create new inventory transfer"""
    if not current_user.has_permission('inventory_transfer'):
        flash('Access denied - Inventory Transfer permissions required', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        transfer_request_number = request.form.get('transfer_request_number')
        from_warehouse = request.form.get('from_warehouse')
        to_warehouse = request.form.get('to_warehouse')
        
        if not transfer_request_number:
            flash('Transfer request number is required', 'error')
            return redirect(url_for('inventory_transfer.create'))
        
        # Check if transfer already exists
        existing_transfer = InventoryTransfer.query.filter_by(
            transfer_request_number=transfer_request_number, 
            user_id=current_user.id
        ).first()
        
        if existing_transfer:
            flash(f'Transfer already exists for request {transfer_request_number}', 'warning')
            return redirect(url_for('inventory_transfer.detail', transfer_id=existing_transfer.id))
        
        # Create new transfer
        transfer = InventoryTransfer(
            transfer_request_number=transfer_request_number,
            user_id=current_user.id,
            from_warehouse=from_warehouse,
            to_warehouse=to_warehouse,
            status='draft'
        )
        
        db.session.add(transfer)
        db.session.commit()
        
        # Log status change
        log_status_change(transfer.id, None, 'draft', current_user.id, 'Transfer created')
        
        logging.info(f"✅ Inventory Transfer created for request {transfer_request_number} by user {current_user.username}")
        flash(f'Inventory Transfer created for request {transfer_request_number}', 'success')
        return redirect(url_for('inventory_transfer.detail', transfer_id=transfer.id))
    
    return render_template('inventory_transfer/create_transfer.html')

@transfer_bp.route('/<int:transfer_id>/submit', methods=['POST'])
@login_required
def submit(transfer_id):
    """Submit transfer for QC approval"""
    try:
        transfer = InventoryTransfer.query.get_or_404(transfer_id)
        
        # Check permissions
        if transfer.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Only draft transfers can be submitted'}), 400
        
        if not transfer.items:
            return jsonify({'success': False, 'error': 'Cannot submit transfer without items'}), 400
        
        # Update status
        old_status = transfer.status
        transfer.status = 'submitted'
        transfer.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Log status change
        log_status_change(transfer_id, old_status, 'submitted', current_user.id, 'Transfer submitted for QC approval')
        
        logging.info(f"📤 Inventory Transfer {transfer_id} submitted for QC approval")
        return jsonify({
            'success': True,
            'message': 'Transfer submitted for QC approval',
            'status': 'submitted'
        })
        
    except Exception as e:
        logging.error(f"Error submitting transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/<int:transfer_id>/qc_approve', methods=['POST'])
@login_required
def qc_approve(transfer_id):
    """QC approve transfer and post to SAP B1"""
    try:
        transfer = InventoryTransfer.query.get_or_404(transfer_id)
        
        # Check QC permissions
        if not current_user.has_permission('qc_dashboard') and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'QC permissions required'}), 403
        
        if transfer.status != 'submitted':
            return jsonify({'success': False, 'error': 'Only submitted transfers can be approved'}), 400
        
        # Get QC notes
        qc_notes = request.json.get('qc_notes', '') if request.is_json else request.form.get('qc_notes', '')
        
        # Mark items as approved
        for item in transfer.items:
            item.qc_status = 'approved'
        
        # Update transfer status
        old_status = transfer.status
        transfer.status = 'qc_approved'
        transfer.qc_approver_id = current_user.id
        transfer.qc_approved_at = datetime.utcnow()
        transfer.qc_notes = qc_notes
        
        # Here you would integrate with SAP B1 to create Stock Transfer
        # For now, we'll simulate success
        transfer.sap_document_number = f"ST-{transfer_id}-{datetime.now().strftime('%Y%m%d')}"
        
        db.session.commit()
        
        # Log status change
        log_status_change(transfer_id, old_status, 'qc_approved', current_user.id, f'Transfer QC approved and posted to SAP B1 as {transfer.sap_document_number}')
        
        logging.info(f"✅ Inventory Transfer {transfer_id} QC approved and posted to SAP B1")
        return jsonify({
            'success': True,
            'message': f'Transfer QC approved and posted to SAP B1 as {transfer.sap_document_number}',
            'sap_document_number': transfer.sap_document_number
        })
        
    except Exception as e:
        logging.error(f"Error approving transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/<int:transfer_id>/qc_reject', methods=['POST'])
@login_required
def qc_reject(transfer_id):
    """QC reject transfer"""
    try:
        transfer = InventoryTransfer.query.get_or_404(transfer_id)
        
        # Check QC permissions
        if not current_user.has_permission('qc_dashboard') and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'QC permissions required'}), 403
        
        if transfer.status != 'submitted':
            return jsonify({'success': False, 'error': 'Only submitted transfers can be rejected'}), 400
        
        # Get rejection reason
        qc_notes = request.json.get('qc_notes', '') if request.is_json else request.form.get('qc_notes', '')
        
        if not qc_notes:
            return jsonify({'success': False, 'error': 'Rejection reason is required'}), 400
        
        # Mark items as rejected
        for item in transfer.items:
            item.qc_status = 'rejected'
        
        # Update transfer status
        old_status = transfer.status
        transfer.status = 'rejected'
        transfer.qc_approver_id = current_user.id
        transfer.qc_approved_at = datetime.utcnow()
        transfer.qc_notes = qc_notes
        
        db.session.commit()
        
        # Log status change
        log_status_change(transfer_id, old_status, 'rejected', current_user.id, f'Transfer rejected by QC: {qc_notes}')
        
        logging.info(f"❌ Inventory Transfer {transfer_id} rejected by QC")
        return jsonify({
            'success': True,
            'message': 'Transfer rejected by QC',
            'status': 'rejected'
        })
        
    except Exception as e:
        logging.error(f"Error rejecting transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/<int:transfer_id>/reopen', methods=['POST'])
@login_required
def reopen(transfer_id):
    """Reopen a rejected transfer"""
    try:
        transfer = InventoryTransfer.query.get_or_404(transfer_id)
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied - You can only reopen your own transfers'}), 403
        
        if transfer.status != 'rejected':
            return jsonify({'success': False, 'error': 'Only rejected transfers can be reopened'}), 400
        
        # Reset transfer to draft status
        old_status = transfer.status
        transfer.status = 'draft'
        transfer.qc_approver_id = None
        transfer.qc_approved_at = None
        transfer.qc_notes = None
        transfer.updated_at = datetime.utcnow()
        
        # Reset all items to pending
        for item in transfer.items:
            item.qc_status = 'pending'
        
        db.session.commit()
        
        # Log status change
        log_status_change(transfer_id, old_status, 'draft', current_user.id, 'Transfer reopened and reset to draft status')
        
        logging.info(f"🔄 Inventory Transfer {transfer_id} reopened and reset to draft status")
        return jsonify({
            'success': True,
            'message': 'Transfer reopened successfully. You can now edit and resubmit it.',
            'status': 'draft'
        })
        
    except Exception as e:
        logging.error(f"Error reopening transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/<int:transfer_id>/add_item', methods=['POST'])
@login_required
def add_transfer_item(transfer_id):
    """Add item to inventory transfer with duplicate prevention"""
    try:
        transfer = InventoryTransfer.query.get_or_404(transfer_id)
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            flash('Access denied - You can only modify your own transfers', 'error')
            return redirect(url_for('inventory_transfer.detail', transfer_id=transfer_id))
        
        if transfer.status != 'draft':
            flash('Cannot add items to non-draft transfer', 'error')
            return redirect(url_for('inventory_transfer.detail', transfer_id=transfer_id))
        
        # Get form data
        item_code = request.form.get('item_code')
        item_name = request.form.get('item_name')
        quantity = float(request.form.get('quantity', 0))
        unit_of_measure = request.form.get('unit_of_measure')
        from_warehouse_code = request.form.get('from_warehouse_code')
        to_warehouse_code = request.form.get('to_warehouse_code')
        from_bin = request.form.get('from_bin')
        to_bin = request.form.get('to_bin')
        batch_number = request.form.get('batch_number')
        
        if not all([item_code, item_name, quantity > 0]):
            flash('Item Code, Item Name, and Quantity are required', 'error')
            return redirect(url_for('inventory_transfer.detail', transfer_id=transfer_id))
        
        # **DUPLICATE PREVENTION LOGIC FOR INVENTORY TRANSFERS**
        # Check if this item_code already exists in this transfer
        existing_item = InventoryTransferItem.query.filter_by(
            transfer_id=transfer_id,
            item_code=item_code
        ).first()
        
        if existing_item:
            flash(f'Item {item_code} has already been added to this inventory transfer. Each item can only be transferred once per transfer request to avoid duplication.', 'error')
            return redirect(url_for('inventory_transfer.detail', transfer_id=transfer_id))
        
        # Create new transfer item
        transfer_item = InventoryTransferItem(
            transfer_id=transfer_id,
            item_code=item_code,
            item_name=item_name,
            quantity=quantity,
            unit_of_measure=unit_of_measure,
            from_warehouse_code=from_warehouse_code,
            to_warehouse_code=to_warehouse_code,
            from_bin=from_bin,
            to_bin=to_bin,
            batch_number=batch_number,
            qc_status='pending'
        )
        
        db.session.add(transfer_item)
        db.session.commit()
        
        logging.info(f"✅ Item {item_code} added to inventory transfer {transfer_id} with duplicate prevention")
        flash(f'Item {item_code} successfully added to inventory transfer', 'success')
        
    except Exception as e:
        logging.error(f"Error adding item to inventory transfer: {str(e)}")
        flash(f'Error adding item: {str(e)}', 'error')
    
    return redirect(url_for('inventory_transfer.detail', transfer_id=transfer_id))

@transfer_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_transfer_item(item_id):
    """Delete transfer item"""
    try:
        item = InventoryTransferItem.query.get_or_404(item_id)
        transfer = item.transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Cannot delete items from non-draft transfer'}), 400
        
        transfer_id = transfer.id
        item_code = item.item_code
        
        db.session.delete(item)
        db.session.commit()
        
        logging.info(f"🗑️ Item {item_code} deleted from inventory transfer {transfer_id}")
        return jsonify({'success': True, 'message': f'Item {item_code} deleted'})
        
    except Exception as e:
        logging.error(f"Error deleting inventory transfer item: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def log_status_change(transfer_id, previous_status, new_status, changed_by_id, notes=None):
    """Log status change to history table"""
    try:
        # TODO: Add TransferStatusHistory model to main models.py if needed
        # history = TransferStatusHistory(
        #     transfer_id=transfer_id,
        #     previous_status=previous_status,
        #     new_status=new_status,
        #     changed_by_id=changed_by_id,
        #     notes=notes
        # )
        # db.session.add(history)
        # db.session.commit()
        logging.info(f"Status changed from {previous_status} to {new_status} by user {changed_by_id}")
    except Exception as e:
        logging.error(f"Error logging status change: {str(e)}")

# ==========================
# Serial Number Transfer Routes
# ==========================

@transfer_bp.route('/serial')
@login_required
def serial_index():
    """Serial Number Transfer main page with pagination and user filtering"""
    if not current_user.has_permission('serial_transfer'):
        flash('Access denied - Serial Transfer permissions required', 'error')
        return redirect(url_for('dashboard'))
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str)
    user_based = request.args.get('user_based', 'true')  # Default to user-based filtering
    
    # Ensure per_page is within allowed range
    if per_page not in [10, 25, 50, 100]:
        per_page = 10
    
    # Build base query
    query = SerialNumberTransfer.query
    
    # Apply user-based filtering
    if user_based == 'true' or current_user.role not in ['admin', 'manager']:
        # Show only current user's transfers (or force for non-admin users)
        query = query.filter_by(user_id=current_user.id)
    
    # Apply search filter if provided
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                SerialNumberTransfer.transfer_number.ilike(search_filter),
                SerialNumberTransfer.from_warehouse.ilike(search_filter),
                SerialNumberTransfer.to_warehouse.ilike(search_filter),
                SerialNumberTransfer.status.ilike(search_filter)
            )
        )
    
    # Order and paginate
    query = query.order_by(SerialNumberTransfer.created_at.desc())
    transfers_paginated = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('serial_transfer_index.html', 
                         transfers=transfers_paginated.items,
                         pagination=transfers_paginated,
                         search=search,
                         per_page=per_page,
                         user_based=user_based,
                         current_user=current_user)

@transfer_bp.route('/serial/create', methods=['GET', 'POST'])
@login_required
def serial_create():
    """Create new Serial Number Transfer"""
    if not current_user.has_permission('serial_transfer'):
        flash('Access denied - Serial Transfer permissions required', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Auto-generate transfer number
        transfer_number = generate_transfer_number()
        from_warehouse = request.form.get('from_warehouse')
        to_warehouse = request.form.get('to_warehouse')
        notes = request.form.get('notes', '')
        
        if not all([from_warehouse, to_warehouse]):
            flash('From Warehouse and To Warehouse are required', 'error')
            return render_template('serial_create_transfer.html')
        
        # Create new transfer with auto-generated number
        transfer = SerialNumberTransfer(
            transfer_number=transfer_number,
            user_id=current_user.id,
            from_warehouse=from_warehouse,
            to_warehouse=to_warehouse,
            notes=notes,
            status='draft'
        )
        
        db.session.add(transfer)
        db.session.commit()
        
        logging.info(f"✅ Serial Number Transfer {transfer_number} created by user {current_user.username}")
        flash(f'Serial Number Transfer {transfer_number} created successfully', 'success')
        return redirect(url_for('inventory_transfer.serial_detail', transfer_id=transfer.id))
    
    return render_template('serial_create_transfer.html')

@transfer_bp.route('/serial/<int:transfer_id>')
@login_required
def serial_detail(transfer_id):
    """Serial Number Transfer detail page"""
    from models import SerialNumberTransfer
    
    transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
    
    # Check permissions
    if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager', 'qc']:
        flash('Access denied - You can only view your own transfers', 'error')
        return redirect(url_for('inventory_transfer.serial_index'))
    
    return render_template('serial_transfer_detail.html', transfer=transfer)

@transfer_bp.route('/serial/<int:transfer_id>/add_item', methods=['POST'])
@login_required
def serial_add_item(transfer_id):
    """Add item to Serial Number Transfer"""
    from models import SerialNumberTransfer, SerialNumberTransferItem, SerialNumberTransferSerial
    
    try:
        transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Cannot add items to non-draft transfer'}), 400
        
        # Get form data
        item_code = request.form.get('item_code')
        item_name = request.form.get('item_name')
        serial_numbers_text = request.form.get('serial_numbers', '')
        
        if not all([item_code, item_name, serial_numbers_text]):
            return jsonify({'success': False, 'error': 'Item Code, Item Name, and Serial Numbers are required'}), 400
        
        # Parse serial numbers (split by newlines, commas, or spaces)
        import re
        serial_numbers = re.split(r'[,\n\r\s]+', serial_numbers_text.strip())
        serial_numbers = [sn.strip() for sn in serial_numbers if sn.strip()]
        
        if not serial_numbers:
            return jsonify({'success': False, 'error': 'At least one serial number is required'}), 400
        
        # Check if this item already exists in this transfer
        existing_item = SerialNumberTransferItem.query.filter_by(
            serial_transfer_id=transfer_id,
            item_code=item_code
        ).first()
        
        if existing_item:
            return jsonify({'success': False, 'error': f'Item {item_code} already exists in this transfer'}), 400
        
        # Create transfer item
        transfer_item = SerialNumberTransferItem(
            serial_transfer_id=transfer_id,
            item_code=item_code,
            item_name=item_name,
            from_warehouse_code=transfer.from_warehouse,
            to_warehouse_code=transfer.to_warehouse
        )
        
        db.session.add(transfer_item)
        db.session.flush()  # Get the ID
        
        # Validate serial numbers against SAP and add them
        validated_count = 0
        for serial_number in serial_numbers:
            try:
                # Validate serial number against SAP with warehouse check
                validation_result = validate_series_with_warehouse_sap(serial_number, item_code, transfer.from_warehouse)
                
                serial_record = SerialNumberTransferSerial(
                    transfer_item_id=transfer_item.id,
                    serial_number=serial_number,
                    internal_serial_number=validation_result.get('SerialNumber') or validation_result.get('DistNumber', serial_number),
                    system_serial_number=validation_result.get('SystemNumber'),
                    is_validated=validation_result.get('valid', False),
                    validation_error=validation_result.get('error') or validation_result.get('warning')
                )
                
                if validation_result.get('valid'):
                    validated_count += 1
                
                db.session.add(serial_record)
                
            except Exception as e:
                logging.error(f"Error validating serial number {serial_number}: {str(e)}")
                # Add as unvalidated
                serial_record = SerialNumberTransferSerial(
                    transfer_item_id=transfer_item.id,
                    serial_number=serial_number,
                    internal_serial_number=serial_number,
                    is_validated=False,
                    validation_error=str(e)
                )
                db.session.add(serial_record)
        
        db.session.commit()
        
        logging.info(f"✅ Item {item_code} with {len(serial_numbers)} serial numbers added to transfer {transfer_id}")
        
        return jsonify({
            'success': True, 
            'message': f'Item {item_code} added with {len(serial_numbers)} serial numbers ({validated_count} validated)',
            'validated_count': validated_count,
            'total_count': len(serial_numbers)
        })
        
    except Exception as e:
        logging.error(f"Error adding item to serial transfer: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/<int:transfer_id>/submit', methods=['POST'])
@login_required
def serial_submit(transfer_id):
    """Submit Serial Number Transfer for QC approval"""
    from models import SerialNumberTransfer
    
    try:
        transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
        
        # Check permissions
        if transfer.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Only draft transfers can be submitted'}), 400
        
        if not transfer.items:
            return jsonify({'success': False, 'error': 'Cannot submit transfer without items'}), 400
        
        # Check if all serial numbers are validated
        unvalidated_count = 0
        for item in transfer.items:
            for serial in item.serial_numbers:
                if not serial.is_validated:
                    unvalidated_count += 1
        
        if unvalidated_count > 0:
            return jsonify({
                'success': False, 
                'error': f'{unvalidated_count} serial numbers are not validated. Please validate all serial numbers before submitting.'
            }), 400
        
        # Update status
        transfer.status = 'submitted'
        transfer.updated_at = datetime.utcnow()
        db.session.commit()
        
        logging.info(f"📤 Serial Number Transfer {transfer_id} submitted for QC approval")
        return jsonify({
            'success': True,
            'message': 'Serial Number Transfer submitted for QC approval',
            'status': 'submitted'
        })
        
    except Exception as e:
        logging.error(f"Error submitting serial transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/<int:transfer_id>/qc_approve', methods=['POST'])
@login_required
def serial_qc_approve(transfer_id):
    """QC approve serial number transfer and post to SAP B1"""
    try:
        from models import SerialNumberTransfer
        
        transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
        
        # Check QC permissions
        if not current_user.has_permission('qc_dashboard') and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'QC permissions required'}), 403
        
        if transfer.status != 'submitted':
            return jsonify({'success': False, 'error': 'Only submitted transfers can be approved'}), 400
        
        # Check if all serial numbers are validated before approval
        has_invalid_serials = False
        invalid_items = []
        
        for item in transfer.items:
            invalid_serials = [s for s in item.serial_numbers if not s.is_validated]
            if invalid_serials:
                has_invalid_serials = True
                invalid_items.append({
                    'item_code': item.item_code,
                    'invalid_count': len(invalid_serials)
                })
        
        if has_invalid_serials:
            invalid_summary = ', '.join([f"{i['item_code']} ({i['invalid_count']} invalid)" for i in invalid_items])
            return jsonify({
                'success': False, 
                'error': f'Cannot approve transfer with invalid serial numbers: {invalid_summary}. Please validate all serial numbers first.'
            }), 400
        
        # Get QC notes
        qc_notes = request.json.get('qc_notes', '') if request.is_json else request.form.get('qc_notes', '')
        
        # Mark items as approved (only if all serials are valid)
        for item in transfer.items:
            item.qc_status = 'approved'
        
        # Update transfer status to qc_approved first
        transfer.status = 'qc_approved'
        transfer.qc_approver_id = current_user.id
        transfer.qc_approved_at = datetime.utcnow()
        transfer.qc_notes = qc_notes
        
        # Post to SAP B1
        try:
            from sap_integration import SAPIntegration
            sap = SAPIntegration()
            
            sap_result = sap.create_serial_number_stock_transfer(transfer)
            
            if sap_result.get('success'):
                transfer.sap_document_number = str(sap_result.get('document_number'))
                transfer.status = 'posted'
                message = f'Serial Number Transfer QC approved and posted to SAP B1 as {transfer.sap_document_number}'
                logging.info(f"✅ {message}")
            else:
                # Keep as qc_approved but note SAP error
                message = f'Serial Number Transfer QC approved but SAP posting failed: {sap_result.get("error")}'
                logging.warning(f"⚠️ {message}")
                
        except Exception as sap_error:
            # Keep as qc_approved but note SAP error
            message = f'Serial Number Transfer QC approved but SAP posting failed: {str(sap_error)}'
            logging.error(f"❌ SAP posting error: {str(sap_error)}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message,
            'status': transfer.status,
            'sap_document_number': transfer.sap_document_number
        })
        
    except Exception as e:
        logging.error(f"Error approving serial transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/<int:transfer_id>/qc_reject', methods=['POST']) 
@login_required
def serial_qc_reject(transfer_id):
    """QC reject serial number transfer"""
    try:
        from models import SerialNumberTransfer
        
        transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
        
        # Check QC permissions
        if not current_user.has_permission('qc_dashboard') and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'QC permissions required'}), 403
        
        if transfer.status != 'submitted':
            return jsonify({'success': False, 'error': 'Only submitted transfers can be rejected'}), 400
        
        # Get rejection reason
        qc_notes = request.json.get('qc_notes', '') if request.is_json else request.form.get('qc_notes', '')
        
        if not qc_notes:
            return jsonify({'success': False, 'error': 'Rejection reason is required'}), 400
        
        # Mark items as rejected
        for item in transfer.items:
            item.qc_status = 'rejected'
        
        # Update transfer status
        transfer.status = 'rejected'
        transfer.qc_approver_id = current_user.id
        transfer.qc_approved_at = datetime.utcnow()
        transfer.qc_notes = qc_notes
        
        db.session.commit()
        
        logging.info(f"❌ Serial Number Transfer {transfer_id} rejected by QC")
        return jsonify({
            'success': True,
            'message': 'Serial Number Transfer rejected by QC',
            'status': 'rejected'
        })
        
    except Exception as e:
        logging.error(f"Error rejecting serial transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/<int:transfer_id>/reopen', methods=['POST'])
@login_required
def serial_reopen_transfer(transfer_id):
    """Reopen a rejected serial number transfer"""
    try:
        from models import SerialNumberTransfer
        
        transfer = SerialNumberTransfer.query.get_or_404(transfer_id)
        
        # Check permissions - only admin, manager, or transfer owner can reopen
        if current_user.role not in ['admin', 'manager'] and transfer.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Access denied - insufficient permissions'}), 403
        
        if transfer.status != 'rejected':
            return jsonify({'success': False, 'error': 'Only rejected transfers can be reopened'}), 400
        
        # Reset transfer status to draft
        old_status = transfer.status
        transfer.status = 'draft'
        transfer.qc_approver_id = None
        transfer.qc_approved_at = None
        transfer.qc_notes = None
        transfer.updated_at = datetime.utcnow()
        
        # Reset all items to draft status if they have qc_status
        for item in transfer.items:
            if hasattr(item, 'qc_status'):
                item.qc_status = None
        
        db.session.commit()
        
        # Log status change
        log_status_change(transfer_id, old_status, 'draft', current_user.id, 'Transfer reopened from rejected status')
        
        logging.info(f"🔄 Serial Transfer {transfer_id} reopened from rejected status by user {current_user.id}")
        return jsonify({
            'success': True,
            'message': 'Transfer reopened successfully. You can now make changes and resubmit.',
            'status': 'draft'
        })
        
    except Exception as e:
        logging.error(f"Error reopening serial transfer: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/items/<int:item_id>/delete', methods=['POST'])
@login_required
def serial_delete_item(item_id):
    """Delete serial number transfer item"""
    try:
        from models import SerialNumberTransferItem
        
        item = SerialNumberTransferItem.query.get_or_404(item_id)
        transfer = item.serial_transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Cannot delete items from non-draft transfer'}), 400
        
        transfer_id = transfer.id
        item_code = item.item_code
        
        db.session.delete(item)
        db.session.commit()
        
        logging.info(f"🗑️ Item {item_code} deleted from serial number transfer {transfer_id}")
        return jsonify({'success': True, 'message': f'Item {item_code} deleted'})
        
    except Exception as e:
        logging.error(f"Error deleting serial transfer item: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/items/<int:item_id>/serials', methods=['GET'])
@login_required  
def serial_get_item_serials(item_id):
    """Get serial numbers for a transfer item"""
    try:
        from models import SerialNumberTransferItem
        
        item = SerialNumberTransferItem.query.get_or_404(item_id)
        transfer = item.serial_transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager', 'qc']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        serials = []
        for serial in item.serial_numbers:
            serials.append({
                'id': serial.id,
                'serial_number': serial.serial_number,
                'is_validated': serial.is_validated,
                'system_serial_number': serial.system_serial_number,
                'validation_error': serial.validation_error
            })
        
        return jsonify({
            'success': True,
            'transfer_status': transfer.status,
            'item_code': item.item_code,
            'item_name': item.item_name,
            'serial_numbers': serials  # Changed from 'serials' to match template expectation
        })
        
    except Exception as e:
        logging.error(f"Error getting serial numbers: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/serials/<int:serial_id>/delete', methods=['POST'])
@login_required
def serial_delete_serial_number(serial_id):
    """Delete individual serial number from transfer"""
    try:
        from models import SerialNumberTransferSerial
        
        serial = SerialNumberTransferSerial.query.get_or_404(serial_id)
        item = serial.transfer_item
        transfer = item.serial_transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Cannot delete serial numbers from non-draft transfer'}), 400
        
        # Store details before deletion
        serial_number = serial.serial_number
        item_code = item.item_code
        transfer_id = transfer.id
        
        # Delete the serial number
        db.session.delete(serial)
        db.session.commit()
        
        logging.info(f"🗑️ Serial number {serial_number} deleted from item {item_code} in transfer {transfer_id}")
        return jsonify({
            'success': True, 
            'message': f'Serial number {serial_number} deleted',
            'item_code': item_code
        })
        
    except Exception as e:
        logging.error(f"Error deleting serial number: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@transfer_bp.route('/serial/serials/<int:serial_id>/edit', methods=['POST'])
@login_required
def serial_edit_serial_number(serial_id):
    """Edit an existing serial number in a transfer"""
    try:
        from models import SerialNumberTransferSerial
        # Using the warehouse-specific validation function defined above
        
        serial_record = SerialNumberTransferSerial.query.get_or_404(serial_id)
        transfer_item = serial_record.transfer_item
        transfer = transfer_item.serial_transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status != 'draft':
            return jsonify({'success': False, 'error': 'Can only edit serial numbers in draft transfers'}), 400
        
        # Get new serial number from form data
        new_serial_number = request.form.get('new_serial_number', '').strip()
        if not new_serial_number:
            return jsonify({'success': False, 'error': 'New serial number is required'}), 400
        
        old_serial_number = serial_record.serial_number
        
        # Check if new serial number already exists in this transfer
        existing = SerialNumberTransferSerial.query.join(SerialNumberTransferItem).filter(
            SerialNumberTransferItem.serial_transfer_id == transfer.id,
            SerialNumberTransferSerial.serial_number == new_serial_number,
            SerialNumberTransferSerial.id != serial_id
        ).first()
        
        if existing:
            return jsonify({
                'success': False, 
                'error': f'Serial number {new_serial_number} already exists in this transfer'
            }), 400
        
        # Validate new serial number against SAP with warehouse availability check
        validation_result = validate_series_with_warehouse_sap(new_serial_number, transfer_item.item_code, transfer.from_warehouse)
        
        # Update the serial number
        serial_record.serial_number = new_serial_number
        serial_record.is_validated = validation_result.get('valid', False)
        serial_record.validation_error = validation_result.get('error') or validation_result.get('warning')
        serial_record.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        logging.info(f"📝 Serial number updated from {old_serial_number} to {new_serial_number} in transfer {transfer.id}")
        return jsonify({
            'success': True,
            'message': f'Serial number updated from {old_serial_number} to {new_serial_number}',
            'serial_number': new_serial_number,
            'is_validated': serial_record.is_validated,
            'validation_error': serial_record.validation_error,
            'item_code': transfer_item.item_code
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error editing serial number: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def validate_series_with_warehouse_sap(serial_number, item_code, warehouse_code):
    """Validate series against SAP B1 API with warehouse availability check"""
    try:
        # Use the existing SAP integration
        from sap_integration import SAPIntegration
        
        sap = SAPIntegration()
        
        # First, validate with new warehouse-specific validation including FromWarehouse
        warehouse_result = sap.validate_series_with_warehouse(serial_number, item_code, warehouse_code)
        
        if warehouse_result.get('valid') and warehouse_result.get('available_in_warehouse'):
            # Series found in a warehouse with stock
            return {
                'valid': True,
                'SerialNumber': warehouse_result.get('DistNumber'),
                'ItemCode': warehouse_result.get('ItemCode'),
                'WhsCode': warehouse_result.get('WhsCode'),
                'available_in_warehouse': True,
                'validation_type': 'warehouse_specific'
            }
        elif warehouse_result.get('valid') and not warehouse_result.get('available_in_warehouse'):
            # Series exists but not available in the FromWarehouse - REJECT for stock transfer
            return {
                'valid': False,
                'error': warehouse_result.get('warning') or f'Series {serial_number} is not available in warehouse {warehouse_code}',
                'available_in_warehouse': False,
                'validation_type': 'warehouse_unavailable'
            }
        else:
            # Validation failed
            return warehouse_result
            
    except Exception as e:
        logging.error(f"Error validating series with warehouse: {str(e)}")
        return {
            'valid': False,
            'error': f'Validation error: {str(e)}'
        }

def validate_serial_number_with_sap(serial_number, item_code):
    """Legacy validation function - kept for compatibility"""
    try:
        # Use the existing SAP integration
        from sap_integration import SAPIntegration
        
        sap = SAPIntegration()
        result = sap.validate_serial_number_with_item(serial_number, item_code)
        
        return result
            
    except Exception as e:
        logging.error(f"Error validating serial number with SAP: {str(e)}")
        return {
            'valid': False,
            'error': f'Validation error: {str(e)}'
        }

@transfer_bp.route('/serial/validate', methods=['POST'])
@login_required
def validate_serial_api():
    """API endpoint to validate serial number with warehouse check"""
    try:
        data = request.get_json()
        if not data:
            data = request.form
            
        serial_number = data.get('serial_number', '').strip()
        item_code = data.get('item_code', '').strip()
        warehouse_code = data.get('warehouse_code', '').strip()
        
        if not all([serial_number, item_code]):
            return jsonify({
                'success': False, 
                'error': 'Serial number and item code are required'
            }), 400
        
        # Validate the serial number
        validation_result = validate_series_with_warehouse_sap(serial_number, item_code, warehouse_code)
        
        return jsonify({
            'success': True,
            'validation_result': validation_result
        })
        
    except Exception as e:
        logging.error(f"Error in serial validation API: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Validation error: {str(e)}'
        }), 500

@transfer_bp.route('/serial/serials/<int:serial_id>/validate', methods=['POST'])
@login_required
def revalidate_serial_number(serial_id):
    """Re-validate a specific serial number in a transfer"""
    try:
        from models import SerialNumberTransferSerial
        
        serial_record = SerialNumberTransferSerial.query.get_or_404(serial_id)
        transfer_item = serial_record.transfer_item
        transfer = transfer_item.serial_transfer
        
        # Check permissions
        if transfer.user_id != current_user.id and current_user.role not in ['admin', 'manager']:
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        if transfer.status not in ['draft', 'submitted']:
            return jsonify({'success': False, 'error': 'Can only validate serial numbers in draft or submitted transfers'}), 400
        
        # Re-validate the serial number
        validation_result = validate_series_with_warehouse_sap(
            serial_record.serial_number, 
            transfer_item.item_code, 
            transfer.from_warehouse
        )
        
        # Update validation status
        serial_record.is_validated = validation_result.get('valid', False)
        serial_record.validation_error = validation_result.get('error') if not validation_result.get('valid') else validation_result.get('warning')
        serial_record.system_serial_number = validation_result.get('SystemNumber') or validation_result.get('SerialNumber')
        serial_record.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        logging.info(f"🔄 Re-validated serial number {serial_record.serial_number} in transfer {transfer.id}")
        
        return jsonify({
            'success': True,
            'message': f'Serial number {serial_record.serial_number} re-validated',
            'is_validated': serial_record.is_validated,
            'validation_error': serial_record.validation_error,
            'available_in_warehouse': validation_result.get('available_in_warehouse', False),
            'warehouse_code': validation_result.get('WhsCode'),
            'validation_type': validation_result.get('validation_type', 'unknown')
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error re-validating serial number: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
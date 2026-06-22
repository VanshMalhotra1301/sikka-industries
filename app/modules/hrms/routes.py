from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db, bcrypt
from app.models import (
    Employee, Attendance, SalarySlip, Factory, LeaveRequest,
    HRNotification, HRAuditLog, User
)
from app.modules.hrms import hrms_bp
from app.utils.decorators import roles_required
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
import calendar, os, math, json

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'uploads', 'employees')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _log_audit(action, entity_type=None, entity_id=None, old_value=None, new_value=None):
    log = HRAuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value
    )
    db.session.add(log)

def _notify(event_type, message, employee_id=None):
    n = HRNotification(event_type=event_type, message=message, employee_id=employee_id)
    db.session.add(n)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: HRMS DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/')
@login_required
@roles_required(['Admin', 'Owner', 'Accountant', 'HR Manager'])
def index():
    today = date.today()
    total_employees = Employee.query.filter_by(status='Active').count()

    # Today's attendance summary
    today_records = Attendance.query.filter_by(date=today).all()
    present_today = sum(1 for a in today_records if a.status in ('Present', 'Late'))
    absent_today = total_employees - present_today
    on_leave_today = sum(1 for a in today_records if a.status == 'On Leave')
    late_today = sum(1 for a in today_records if a.status == 'Late')
    overtime_today = sum(1 for a in today_records if a.overtime_hours and a.overtime_hours > 0)

    # Currently checked-in (no check-out yet)
    checked_in = Attendance.query.filter(
        Attendance.date == today,
        Attendance.check_in != None,
        Attendance.check_out == None
    ).all()

    # Pending leave requests
    pending_leaves = LeaveRequest.query.filter_by(status='Pending').count()

    # Unread notifications
    unread_notifications = HRNotification.query.filter_by(is_read=False).order_by(
        HRNotification.created_at.desc()
    ).limit(20).all()

    # Monthly payroll cost (current month)
    current_month_slips = SalarySlip.query.filter_by(month=today.month, year=today.year).all()
    monthly_payroll = sum(s.net_salary for s in current_month_slips)

    # Department distribution
    departments = db.session.query(
        Employee.department, db.func.count(Employee.id)
    ).filter_by(status='Active').group_by(Employee.department).all()
    dept_labels = [d[0] or 'Unassigned' for d in departments]
    dept_values = [d[1] for d in departments]

    # Attendance trend (last 7 days)
    trend_labels = []
    trend_present = []
    trend_absent = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        trend_labels.append(d.strftime('%d %b'))
        day_att = Attendance.query.filter_by(date=d).all()
        p = sum(1 for a in day_att if a.status in ('Present', 'Late'))
        trend_present.append(p)
        trend_absent.append(total_employees - p)

    return render_template(
        'modules/hrms/index.html',
        total_employees=total_employees,
        present_today=present_today,
        absent_today=absent_today,
        on_leave_today=on_leave_today,
        late_today=late_today,
        overtime_today=overtime_today,
        checked_in=checked_in,
        pending_leaves=pending_leaves,
        monthly_payroll=monthly_payroll,
        unread_notifications=unread_notifications,
        dept_labels=dept_labels,
        dept_values=dept_values,
        trend_labels=trend_labels,
        trend_present=trend_present,
        trend_absent=trend_absent,
        today=today
    )


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: FACTORY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/factories')
@login_required
@roles_required(['Admin', 'Owner'])
def factories():
    all_factories = Factory.query.order_by(Factory.name).all()
    return render_template('modules/hrms/factories.html', factories=all_factories)


@hrms_bp.route('/factories/add', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Owner'])
def add_factory():
    if request.method == 'POST':
        factory = Factory(
            name=request.form.get('name'),
            address=request.form.get('address'),
            latitude=float(request.form.get('latitude') or 0),
            longitude=float(request.form.get('longitude') or 0),
            attendance_radius=int(request.form.get('attendance_radius') or 200)
        )
        db.session.add(factory)
        _log_audit('Factory Created', 'Factory', new_value=factory.name)
        db.session.commit()
        flash(f'Factory "{factory.name}" created successfully.', 'success')
        return redirect(url_for('hrms.factories'))
    return render_template('modules/hrms/add_factory.html')


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: EMPLOYEE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/employees')
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager', 'Accountant'])
def employees():
    all_employees = Employee.query.order_by(Employee.employee_code).all()
    return render_template('modules/hrms/employees.html', employees=all_employees)


@hrms_bp.route('/employees/add', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager'])
def add_employee():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        designation = request.form.get('designation')
        department = request.form.get('department')
        base_salary = float(request.form.get('base_salary') or 0)
        employment_type = request.form.get('employment_type', 'Full-Time')
        factory_id = request.form.get('factory_id') or None
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        joined_at_str = request.form.get('joined_at')
        try:
            joined_at = datetime.strptime(joined_at_str, '%Y-%m-%d').date() if joined_at_str else date.today()
        except ValueError:
            joined_at = date.today()

        # Auto-generate Employee ID: EMP0001, EMP0002, ...
        last_emp = Employee.query.order_by(Employee.id.desc()).first()
        if last_emp:
            try:
                last_num = int(last_emp.employee_code.replace('EMP', ''))
                new_num = last_num + 1
            except:
                new_num = last_emp.id + 1
        else:
            new_num = 1
        emp_code = f"EMP{new_num:04d}"

        # Create User account for employee login
        user_id = None
        if username and password:
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash(f'Username "{username}" is already taken.', 'danger')
                all_factories = Factory.query.filter_by(is_active=True).all()
                return render_template('modules/hrms/add_employee.html', factories=all_factories)

            hashed = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(username=username, password_hash=hashed, role='Employee', is_active=True)
            db.session.add(user)
            db.session.flush()
            user_id = user.id

        # Handle photo upload
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = f"{emp_code}_{secure_filename(file.filename)}"
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                photo_filename = filename

        emp = Employee(
            employee_code=emp_code, name=name, photo_filename=photo_filename,
            phone=phone, email=email, address=address,
            designation=designation, department=department,
            base_salary=base_salary, employment_type=employment_type,
            joined_at=joined_at, status='Active',
            factory_id=int(factory_id) if factory_id else None,
            user_id=user_id
        )
        db.session.add(emp)
        _log_audit('Employee Created', 'Employee', new_value=f'{emp_code} - {name}')
        db.session.commit()
        flash(f'Employee {name} created with ID {emp_code}.', 'success')
        return redirect(url_for('hrms.employees'))

    all_factories = Factory.query.filter_by(is_active=True).all()
    return render_template('modules/hrms/add_employee.html', factories=all_factories)


@hrms_bp.route('/employees/<int:emp_id>')
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager', 'Accountant'])
def view_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    recent_attendance = Attendance.query.filter_by(employee_id=emp_id).order_by(Attendance.date.desc()).limit(30).all()
    leave_requests = LeaveRequest.query.filter_by(employee_id=emp_id).order_by(LeaveRequest.applied_at.desc()).all()
    salary_slips = SalarySlip.query.filter_by(employee_id=emp_id).order_by(SalarySlip.year.desc(), SalarySlip.month.desc()).all()
    return render_template('modules/hrms/view_employee.html', emp=emp, recent_attendance=recent_attendance,
                           leave_requests=leave_requests, salary_slips=salary_slips)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: ATTENDANCE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/attendance')
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager'])
def attendance_admin():
    today = date.today()
    target_date_str = request.args.get('date', today.strftime('%Y-%m-%d'))
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except:
        target_date = today

    records = db.session.query(Attendance, Employee).join(Employee).filter(
        Attendance.date == target_date
    ).order_by(Employee.name).all()

    return render_template('modules/hrms/attendance_admin.html', records=records, target_date=target_date)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: LEAVE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/leaves')
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager'])
def leaves_admin():
    pending = LeaveRequest.query.filter_by(status='Pending').order_by(LeaveRequest.applied_at.desc()).all()
    history = LeaveRequest.query.filter(LeaveRequest.status != 'Pending').order_by(LeaveRequest.actioned_at.desc()).limit(50).all()
    return render_template('modules/hrms/leaves_admin.html', pending=pending, history=history)


@hrms_bp.route('/leaves/<int:leave_id>/action', methods=['POST'])
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager'])
def leave_action(leave_id):
    leave = LeaveRequest.query.get_or_404(leave_id)
    action = request.form.get('action')

    if action == 'approve':
        leave.status = 'Approved'
        leave.approved_by = current_user.id
        leave.actioned_at = datetime.utcnow()

        # Deduct leave balance
        emp = leave.employee
        if leave.leave_type == 'Casual':
            emp.casual_leave_balance = max(0, (emp.casual_leave_balance or 0) - leave.days)
        elif leave.leave_type == 'Sick':
            emp.sick_leave_balance = max(0, (emp.sick_leave_balance or 0) - leave.days)
        elif leave.leave_type == 'Emergency':
            emp.emergency_leave_balance = max(0, (emp.emergency_leave_balance or 0) - leave.days)

        # Mark attendance as On Leave for those dates
        current_date = leave.start_date
        while current_date <= leave.end_date:
            att = Attendance.query.filter_by(employee_id=emp.id, date=current_date).first()
            if not att:
                att = Attendance(employee_id=emp.id, date=current_date, factory_id=emp.factory_id)
                db.session.add(att)
            att.status = 'On Leave'
            current_date += timedelta(days=1)

        _log_audit('Leave Approved', 'LeaveRequest', leave_id, new_value=f'{leave.leave_type} for {leave.employee.name}')
        flash(f'Leave approved for {leave.employee.name}.', 'success')

    elif action == 'reject':
        leave.status = 'Rejected'
        leave.approved_by = current_user.id
        leave.actioned_at = datetime.utcnow()
        _log_audit('Leave Rejected', 'LeaveRequest', leave_id)
        flash(f'Leave rejected for {leave.employee.name}.', 'info')

    db.session.commit()
    return redirect(url_for('hrms.leaves_admin'))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: PAYROLL
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/payroll', methods=['GET', 'POST'])
@login_required
@roles_required(['Admin', 'Owner', 'HR Manager', 'Accountant'])
def payroll():
    today = date.today()
    month = int(request.args.get('month', today.month))
    year = int(request.args.get('year', today.year))
    month_name = calendar.month_name[month]

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            employees = Employee.query.filter_by(status='Active').all()
            _, days_in_month = calendar.monthrange(year, month)
            start_d = date(year, month, 1)
            end_d = date(year, month, days_in_month)
            count = 0

            for emp in employees:
                existing = SalarySlip.query.filter_by(employee_id=emp.id, month=month, year=year).first()
                if existing:
                    continue

                att_records = Attendance.query.filter(
                    Attendance.employee_id == emp.id,
                    Attendance.date.between(start_d, end_d)
                ).all()

                days_present = sum(1 for a in att_records if a.status in ('Present', 'Late'))
                days_absent = sum(1 for a in att_records if a.status == 'Absent')
                total_ot = sum(a.overtime_hours or 0 for a in att_records)

                per_day = emp.base_salary / days_in_month if days_in_month > 0 else 0
                per_hour_ot = per_day / 8 * 1.5  # 1.5x overtime rate
                deductions = days_absent * per_day
                overtime_pay = total_ot * per_hour_ot
                net = emp.base_salary - deductions + overtime_pay

                slip = SalarySlip(
                    employee_id=emp.id, month=month, year=year,
                    working_days=days_in_month, days_present=days_present, days_absent=days_absent,
                    total_overtime_hours=total_ot,
                    basic_salary=emp.base_salary, overtime_pay=round(overtime_pay, 2),
                    deductions=round(deductions, 2), net_salary=round(net, 2),
                    status='Generated'
                )
                db.session.add(slip)
                count += 1

            _log_audit('Payroll Generated', 'SalarySlip', new_value=f'{month_name} {year} ({count} slips)')
            _notify('salary_generated', f'Payroll generated for {month_name} {year}: {count} slips')
            db.session.commit()
            flash(f'Generated {count} salary slips for {month_name} {year}.', 'success')

    slips = SalarySlip.query.filter_by(month=month, year=year).all()
    total_payroll = sum(s.net_salary for s in slips)
    return render_template('modules/hrms/payroll.html', slips=slips, month=month, year=year,
                           month_name=month_name, total_payroll=total_payroll)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: NOTIFICATIONS & AUDIT
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/audit-log')
@login_required
@roles_required(['Admin', 'Owner'])
def audit_log():
    logs = HRAuditLog.query.order_by(HRAuditLog.timestamp.desc()).limit(100).all()
    return render_template('modules/hrms/audit_log.html', logs=logs)


# ══════════════════════════════════════════════════════════════════════════════
# EMPLOYEE PORTAL — MOBILE-FIRST
# ══════════════════════════════════════════════════════════════════════════════
@hrms_bp.route('/my')
@login_required
def employee_portal():
    """Employee self-service dashboard — mobile-first."""
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        flash('No employee profile linked to this account.', 'danger')
        return redirect(url_for('dashboard.index'))

    today = date.today()
    today_att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()

    # Current month stats
    _, days_in_month = calendar.monthrange(today.year, today.month)
    start_d = date(today.year, today.month, 1)
    month_att = Attendance.query.filter(
        Attendance.employee_id == emp.id,
        Attendance.date.between(start_d, today)
    ).all()
    days_present = sum(1 for a in month_att if a.status in ('Present', 'Late'))
    days_absent = sum(1 for a in month_att if a.status == 'Absent')

    # Current month salary (if generated)
    current_slip = SalarySlip.query.filter_by(
        employee_id=emp.id, month=today.month, year=today.year
    ).first()

    # Leave balances
    pending_leaves = LeaveRequest.query.filter_by(employee_id=emp.id, status='Pending').count()

    return render_template(
        'modules/hrms/employee_portal.html',
        emp=emp, today=today, today_att=today_att,
        days_present=days_present, days_absent=days_absent,
        days_in_month=days_in_month,
        current_slip=current_slip,
        pending_leaves=pending_leaves
    )


# ── Employee: Check-In API ──
@hrms_bp.route('/my/checkin', methods=['POST'])
@login_required
def employee_checkin():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        return jsonify({'success': False, 'message': 'No employee profile found.'}), 400

    today = date.today()
    existing = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
    if existing and existing.check_in:
        return jsonify({'success': False, 'message': 'Already checked in today.'}), 400

    lat = request.json.get('latitude')
    lng = request.json.get('longitude')
    device_info = request.json.get('device_info', '')

    # GPS verification
    location_verified = False
    reject_msg = None
    if emp.factory and emp.factory.latitude and emp.factory.longitude and lat and lng:
        distance = _haversine(float(lat), float(lng), emp.factory.latitude, emp.factory.longitude)
        if distance <= emp.factory.attendance_radius:
            location_verified = True
        else:
            reject_msg = f'You are {int(distance)}m away from {emp.factory.name}. Allowed radius: {emp.factory.attendance_radius}m.'
            _notify('attendance_outside_radius',
                    f'{emp.name} ({emp.employee_code}) attempted check-in {int(distance)}m from {emp.factory.name}.',
                    emp.id)
    else:
        # No factory assigned or no GPS — allow without verification
        location_verified = True

    if not location_verified:
        db.session.commit()  # commit notification
        return jsonify({'success': False, 'message': reject_msg or 'You are not within the assigned factory location.'}), 403

    now = datetime.utcnow()
    if not existing:
        existing = Attendance(employee_id=emp.id, date=today, factory_id=emp.factory_id)
        db.session.add(existing)

    existing.check_in = now
    existing.checkin_latitude = float(lat) if lat else None
    existing.checkin_longitude = float(lng) if lng else None
    existing.location_verified = location_verified
    existing.device_info = device_info
    existing.status = 'Present'

    _notify('check_in', f'{emp.name} ({emp.employee_code}) checked in at {now.strftime("%H:%M")}.', emp.id)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Check-in successful!', 'time': now.strftime('%I:%M %p')})


# ── Employee: Check-Out API ──
@hrms_bp.route('/my/checkout', methods=['POST'])
@login_required
def employee_checkout():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        return jsonify({'success': False, 'message': 'No employee profile found.'}), 400

    today = date.today()
    att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
    if not att or not att.check_in:
        return jsonify({'success': False, 'message': 'You have not checked in today.'}), 400
    if att.check_out:
        return jsonify({'success': False, 'message': 'Already checked out today.'}), 400

    now = datetime.utcnow()
    att.check_out = now

    # Calculate working & overtime hours
    delta = (now - att.check_in).total_seconds() / 3600
    att.working_hours = round(delta, 2)
    att.overtime_hours = round(max(0, delta - 8), 2)

    _notify('check_out', f'{emp.name} ({emp.employee_code}) checked out at {now.strftime("%H:%M")}. Worked {att.working_hours:.1f}h.', emp.id)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Check-out successful!', 'hours': att.working_hours})


# ── Employee: Attendance History ──
@hrms_bp.route('/my/attendance')
@login_required
def employee_attendance_history():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        flash('No employee profile linked.', 'danger')
        return redirect(url_for('dashboard.index'))

    records = Attendance.query.filter_by(employee_id=emp.id).order_by(Attendance.date.desc()).limit(60).all()
    return render_template('modules/hrms/employee_attendance.html', emp=emp, records=records)


# ── Employee: Salary Slips ──
@hrms_bp.route('/my/salary')
@login_required
def employee_salary():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        flash('No employee profile linked.', 'danger')
        return redirect(url_for('dashboard.index'))

    slips = SalarySlip.query.filter_by(employee_id=emp.id).order_by(SalarySlip.year.desc(), SalarySlip.month.desc()).all()
    return render_template('modules/hrms/employee_salary.html', emp=emp, slips=slips)


# ── Employee: Apply Leave ──
@hrms_bp.route('/my/leave', methods=['GET', 'POST'])
@login_required
def employee_leave():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        flash('No employee profile linked.', 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        leave_type = request.form.get('leave_type')
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        reason = request.form.get('reason')

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
        except:
            flash('Invalid dates.', 'danger')
            return redirect(url_for('hrms.employee_leave'))

        days = (end_date - start_date).days + 1
        if days <= 0:
            flash('End date must be after start date.', 'danger')
            return redirect(url_for('hrms.employee_leave'))

        leave = LeaveRequest(
            employee_id=emp.id, leave_type=leave_type,
            start_date=start_date, end_date=end_date, days=days, reason=reason
        )
        db.session.add(leave)
        _notify('leave_request', f'{emp.name} ({emp.employee_code}) applied for {leave_type} Leave ({days} days).', emp.id)
        db.session.commit()
        flash(f'Leave application submitted for {days} day(s).', 'success')
        return redirect(url_for('hrms.employee_leave'))

    leaves = LeaveRequest.query.filter_by(employee_id=emp.id).order_by(LeaveRequest.applied_at.desc()).all()
    return render_template('modules/hrms/employee_leave.html', emp=emp, leaves=leaves)


# ── Employee: Profile ──
@hrms_bp.route('/my/profile')
@login_required
def employee_profile():
    emp = Employee.query.filter_by(user_id=current_user.id).first()
    if not emp:
        flash('No employee profile linked.', 'danger')
        return redirect(url_for('dashboard.index'))
    return render_template('modules/hrms/employee_profile.html', emp=emp)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY: Haversine formula for GPS distance
# ══════════════════════════════════════════════════════════════════════════════
def _haversine(lat1, lon1, lat2, lon2):
    """Returns distance in metres between two GPS points."""
    R = 6371000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

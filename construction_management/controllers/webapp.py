from odoo import http, fields, _
from odoo.http import request
import json
import logging
import io
import xlsxwriter
import base64
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from datetime import datetime, timedelta, date

_logger = logging.getLogger(__name__)

class ConstructionWebApp(http.Controller):

    def _validate_token(self, token):
        session = request.env['construction.webapp.session'].sudo().search([('token', '=', token)], limit=1)
        if not session or not session.is_valid():
            return None
        return session.user_id

    @http.route('/webapp/dashboard', type='http', auth='public', website=False)
    def webapp_dashboard(self, token=None, **kwargs):
        if not token:
             return "Access Denied: No Token"
        
        user = self._validate_token(token)
        if not user:
            return "Access Denied: Invalid or Expired Session. Please close and re-open from Telegram."

        # Fetch allowed projects for this user logic can be improved later
        # For 'client' role, usually limited to partner's project
        # But we will handle data fetching via API
        
        return request.render('construction_management.webapp_dashboard', {
            'token': token,
            'user': user,
        })

    @http.route('/webapp/api/summary', type='http', auth='public', methods=['GET'], csrf=False)
    def api_summary(self, token=None, project_id=None, period='all', custom_start=None, custom_end=None, **kwargs):
        user = self._validate_token(token)
        if not user:
            return json.dumps({'error': 'Unauthorized'})

        try:
            pid = int(project_id) if project_id else False
        except:
            pid = False
            
        if not pid:
             # Just return list of projects if no ID 
             projects = request.env['construction.project'].with_user(user).search([])
             if not projects:
                 return json.dumps({'error': 'No Projects Found'})
             pid = projects[0].id

        project = request.env['construction.project'].with_user(user).browse(pid)
        if not project.exists():
             return json.dumps({'error': 'Project Not Found'})

        # Date Filtering Logic
        today = fields.Date.today()
        date_from = None
        date_to = None
        
        # Default to month if 'all' passed? User requested defaults. But let's stick to logic passed.
        # Frontend defaults can be handled there, but if period='all', we fetch all.
        
        if period == 'today':
            date_from = today
            date_to = today
        elif period == 'week':
            date_from = today - timedelta(days=today.weekday()) # Start of week (Mon)
            date_to = today
        elif period == 'month':
            date_from = today.replace(day=1)
            date_to = today
        elif period == 'custom' and custom_start and custom_end:
            date_from = fields.Date.from_string(custom_start)
            date_to = fields.Date.from_string(custom_end)
        else:
             # Default to All Time (no filters)
             pass

        # 1. Income Data (Correct Auth)
        income_domain = [('project_id', '=', project.id)]
        if date_from: income_domain.append(('date', '>=', date_from))
        if date_to: income_domain.append(('date', '<=', date_to))
        
        incomes = request.env['construction.project.income'].with_user(user).search(income_domain, order='date desc')
        
        # Group Income by Date
        income_grouped = {}
        total_income_period = 0.0
        for inc in incomes:
            d_str = inc.date.strftime('%Y-%m-%d')
            if d_str not in income_grouped:
                income_grouped[d_str] = {'date': d_str, 'total': 0, 'items': []}
            
            income_grouped[d_str]['total'] += inc.amount
            income_grouped[d_str]['items'].append({
                'id': inc.id,
                'description': inc.description,
                'amount': inc.amount
            })
            total_income_period += inc.amount

        # 2. Expense Data (Correct Auth)
        # Materials
        mat_domain = [('stage_id.project_id', '=', project.id)]
        if date_from: mat_domain.append(('date', '>=', date_from))
        if date_to: mat_domain.append(('date', '<=', date_to))
        
        materials = request.env['construction.stage.material'].with_user(user).search(mat_domain)
        
        # Services
        svc_domain = [('stage_id.project_id', '=', project.id)]
        if date_from: svc_domain.append(('date', '>=', date_from))
        if date_to: svc_domain.append(('date', '<=', date_to))
        
        services = request.env['construction.stage.service'].with_user(user).search(svc_domain)

        total_expense_period = sum(materials.mapped('total_cost')) + sum(services.mapped('total_cost'))
        total_material = sum(materials.mapped('total_cost'))
        total_service = sum(services.mapped('total_cost'))
        
        # Group Expenses by Stage
        expense_by_stage = {}
        
        # Process Materials
        for m in materials:
            sid = m.stage_id.id if m.stage_id else 0
            sname = m.stage_id.name if m.stage_id else "Stage belgilanmagan"
            
            if sid not in expense_by_stage:
                expense_by_stage[sid] = {'name': sname, 'total': 0, 'items': []}
            
            expense_by_stage[sid]['total'] += m.total_cost
            expense_by_stage[sid]['items'].append({
                'type': 'material',
                'name': m.product_id.name,
                'amount': m.total_cost,
                'date': m.date.strftime('%Y-%m-%d'),
                'status': m.state, 
                'color': 'blue'
            })

        # Process Services
        for s in services:
            sid = s.stage_id.id if s.stage_id else 0
            sname = s.stage_id.name if s.stage_id else "Stage belgilanmagan"
            
            if sid not in expense_by_stage:
                expense_by_stage[sid] = {'name': sname, 'total': 0, 'items': []}
            
            expense_by_stage[sid]['total'] += s.total_cost
            expense_by_stage[sid]['items'].append({
                'type': 'service',
                'name': s.service_id.name + (f" ({s.description})" if s.description else ""),
                'amount': s.total_cost,
                'date': s.date.strftime('%Y-%m-%d'),
                'status': 'Done' if s.is_done else 'Planned',
                'color': 'yellow'
            })

        # 3. Stages List (For Progress Tab)
        stages = request.env['construction.stage'].with_user(user).search([('project_id', '=', project.id)], order='id')
        stages_data = []
        for stage in stages:
            # Fetch Tasks for this stage
            tasks_data = []
            total_services = 0
            done_services = 0
            
            stage_images = []
            
            for task in stage.task_ids:
                # Handle Image Tasks
                task_name_lower = (task.name or '').lower()
                if 'rasmlar' in task_name_lower:
                    try:
                        for img in task.image_ids:
                             stage_images.append({
                                 'id': img.id,
                                 'url': f'/webapp/api/image/{img.id}?token={token}',
                                 'name': img.name or "Rasm"
                             })
                    except Exception as e:
                        _logger.error(f"Error fetching images for task {task.id}: {str(e)}")
                    continue # Skip adding to main task list

                # Filter: Exclude material tasks
                if 'материал' in task_name_lower:
                    continue  # Skip material tasks
                
                # We only want tasks that have checklist items (services)
                services_data = []
                for svc in task.service_ids:
                    total_services += 1
                    if svc.is_done:
                        done_services += 1
                    
                    services_data.append({
                        'id': svc.id,
                        'name': svc.service_id.name,
                        'description': svc.description or "",
                        'quantity': svc.quantity,
                        'unit': svc.construction_uom_id.name or "",
                        'price': svc.unit_price,
                        'total': svc.total_cost,
                        'is_done': svc.is_done
                    })
                
                # Only add task if it has services to show
                if services_data:
                    tasks_data.append({
                        'id': task.id,
                        'name': task.name,
                        'progress': task.progress,
                        'items': services_data
                    })

            # Calculate stage progress from services
            stage_progress = (done_services / total_services * 100) if total_services > 0 else 0
            
            # Auto-determine status based on progress
            if stage_progress >= 100:
                computed_status = 'completed'
            elif stage_progress > 0:
                computed_status = 'in_progress'
            else:
                computed_status = 'pending'
            
            stages_data.append({
                'id': stage.id,
                'name': stage.name,
                'status': computed_status,  # Use computed status instead of stage.state
                'progress': round(stage_progress, 1),  # Use calculated progress
                'type': stage.stage_type,
                'tasks': tasks_data, # Nested Tasks
                'images': stage_images # Stage Images
            })

        all_time_income = project.total_income
        all_time_expense = project.total_expense
        balance = project.balance

        data = {
            'project': {
                'id': project.id,
                'name': project.name,
                'balance': balance, # All time
                'income_period': total_income_period,
                'expense_period': total_expense_period,
                'material_total': total_material,
                'service_total': total_service,
                'last_payment_date': incomes[0].date.strftime('%Y-%m-%d') if incomes else None,
                'payment_count': len(incomes)
            },
            'stages': stages_data,
            'income_grouped': list(income_grouped.values()),
            'expense_by_stage': list(expense_by_stage.values())
        }
        
        return json.dumps(data, default=str)

    @http.route('/webapp/api/report/download', type='http', auth='public')
    def download_report(self, token=None, project_id=None, report_type='pdf', period='all', custom_start=None, custom_end=None, **kwargs):
        user = self._validate_token(token)
        if not user:
             return http.Response("Unauthorized", status=401)
             
        try:
            pid = int(project_id)
            project = request.env['construction.project'].with_user(user).browse(pid)
            if not project.exists():
                 return http.Response("Project not found", status=404)
        except:
             return http.Response("Invalid Project", status=400)

        # Date Filter for Report
        date_from = None
        date_to = None
        today = fields.Date.today()
        
        period_label = "Barcha davr"
        if period == 'today':
            date_from = today
            date_to = today
            period_label = f"{today}"
        elif period == 'week':
            date_from = today - timedelta(days=today.weekday())
            date_to = today
            period_label = f"{date_from} - {today}"
        elif period == 'month':
            date_from = today.replace(day=1)
            date_to = today
            period_label = f"{date_from} - {today}"
        elif period == 'custom' and custom_start and custom_end:
            date_from = fields.Date.from_string(custom_start)
            date_to = fields.Date.from_string(custom_end)
            period_label = f"{custom_start} - {custom_end}"

        # Generate Report
        if report_type == 'pdf':
            file_content = self._generate_pdf_report(project, date_from, date_to, period_label)
            filename = f"{project.name}_Report_{period}.pdf"
            content_type = 'application/pdf'
        elif report_type == 'excel':
            file_content = self._generate_excel_report(project, date_from, date_to, period_label)
            filename = f"{project.name}_Report_{period}.xlsx"
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
             return http.Response("Invalid Report Type", status=400)

        # Log Report (Optional / Phase 2b)
        # self.env['ir.attachment'].create({...})

        return request.make_response(
            file_content,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'attachment; filename={filename}')
            ]
        )

    @http.route('/webapp/api/request_report', type='json', auth='public', methods=['POST'], csrf=False)
    def request_report_via_bot(self, token=None, project_id=None, report_type='pdf', **kwargs):
        """Generate report and send it via Telegram bot"""
        _logger.info(f"🔔 request_report_via_bot called: project_id={project_id}, report_type={report_type}")
        user = self._validate_token(token)
        if not user:
            _logger.error("❌ Unauthorized - invalid token")
            return {'success': False, 'error': 'Unauthorized'}
        
        try:
            pid = int(project_id)
            project = request.env['construction.project'].with_user(user).browse(pid)
            if not project.exists():
                return {'success': False, 'error': 'Project not found'}
        except:
            return {'success': False, 'error': 'Invalid project ID'}
        
        # Get user's Telegram chat_id directly from res.users
        if not user.telegram_chat_id:
            _logger.error(f"❌ Telegram chat_id not found for user={user.name}")
            return {'success': False, 'error': 'Telegram not linked'}
        
        chat_id = user.telegram_chat_id
        _logger.info(f"✅ Found telegram chat_id: {chat_id}")
        
        
        try:
            # Generate report
            date_from = None
            date_to = None
            period_label = "Barcha davr"
            
            if report_type == 'pdf':
                file_content = self._generate_pdf_report(project, date_from, date_to, period_label)
                filename = f"{project.name}_Hisobot.pdf"
                caption = f"📄 PDF Hisobot\n\nLoyiha: {project.name}\nMijoz: {project.customer_id.name}"
            elif report_type == 'excel':
                file_content = self._generate_excel_report(project, date_from, date_to, period_label)
                filename = f"{project.name}_Hisobot.xlsx"
                caption = f"📊 Excel Hisobot\n\nLoyiha: {project.name}\nMijoz: {project.customer_id.name}"
            else:
                return {'success': False, 'error': 'Invalid report type'}
            
            # Send via bot (AbstractModel - don't search, call directly)
            try:
                request.env['construction.telegram.bot'].sudo()._send_document(
                    chat_id=chat_id,
                    doc_data=file_content,
                    filename=filename,
                    caption=caption
                )
                return {'success': True, 'message': 'Report sent to Telegram'}
            except Exception as send_error:
                _logger.error(f"Error sending document: {str(send_error)}")
                return {'success': False, 'error': f'Send failed: {str(send_error)}'}
                
        except Exception as e:
            _logger.error(f"Error generating report: {str(e)}")
            return {'success': False, 'error': str(e)}

    def _get_report_data(self, project, date_from, date_to):
        """Helper to fetch filtered data for reports"""
        income_domain = [('project_id', '=', project.id)]
        mat_domain = [('stage_id.project_id', '=', project.id)]
        svc_domain = [('stage_id.project_id', '=', project.id)]
        
        if date_from:
            income_domain.append(('date', '>=', date_from))
            mat_domain.append(('date', '>=', date_from))
            svc_domain.append(('date', '>=', date_from))
        if date_to:
            income_domain.append(('date', '<=', date_to))
            mat_domain.append(('date', '<=', date_to))
            svc_domain.append(('date', '<=', date_to))

        incomes = request.env['construction.project.income'].sudo().search(income_domain, order='date desc')
        materials = request.env['construction.stage.material'].sudo().search(mat_domain, order='date desc')
        services = request.env['construction.stage.service'].sudo().search(svc_domain, order='date desc')
        
        return incomes, materials, services

    @http.route('/webapp/api/image/<int:image_id>', type='http', auth='public')
    def get_image(self, image_id, token=None, **kwargs):
        """Securely serve specific image with token auth"""
        user = self._validate_token(token)
        if not user:
            return http.Response("Unauthorized", status=403)
            
        image = request.env['construction.stage.image'].sudo().browse(image_id)
        if not image.exists() or not image.image:
            return http.Response("Not Found", status=404)
            
        image_content = base64.b64decode(image.image)
        return request.make_response(image_content, headers=[
            ('Content-Type', 'image/jpeg'),
            ('Cache-Control', 'max-age=3600')
        ])

    def _generate_pdf_report(self, project, date_from, date_to, period_label):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        elements = []
        styles = getSampleStyleSheet()
        
        # --- Custom Styles ---
        title_style = ParagraphStyle(
            'ReportTitle', 
            parent=styles['Heading1'], 
            fontSize=24, 
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=10
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle', 
            parent=styles['Normal'], 
            fontSize=12, 
            textColor=colors.HexColor('#7F8C8D'),
            spaceAfter=30
        )
        header_label = ParagraphStyle(
            'HeaderLabel',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#95A5A6')
        )
        header_value = ParagraphStyle(
            'HeaderValue',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#2C3E50'),
            fontName='Helvetica-Bold'
        )
        card_label = ParagraphStyle(
            'CardLabel',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#7F8C8D'),
            alignment=TA_CENTER
        )
        card_value_income = ParagraphStyle(
            'CardValueIncome',
            parent=styles['Normal'],
            fontSize=16,
            textColor=colors.HexColor('#27AE60'),
            fontName='Helvetica-Bold',
            alignment=TA_CENTER
        )
        card_value_expense = ParagraphStyle(
            'CardValueExpense',
            parent=styles['Normal'],
            fontSize=16,
            textColor=colors.HexColor('#C0392B'),
            fontName='Helvetica-Bold',
            alignment=TA_CENTER
        )
        card_value_balance = ParagraphStyle(
            'CardValueBalance',
            parent=styles['Normal'],
            fontSize=16,
            textColor=colors.HexColor('#2980B9'),
            fontName='Helvetica-Bold',
            alignment=TA_CENTER
        )
        
        # --- Header Section ---
        elements.append(Paragraph(f"{project.name}", title_style))
        elements.append(Paragraph(f"Moliya Hisoboti - {period_label}", subtitle_style))
        
        # Info Grid
        info_data = [
            [Paragraph("MIJOZ:", header_label), Paragraph(project.customer_id.name, header_value),
             Paragraph("SANA:", header_label), Paragraph(fields.Date.today().strftime('%d.%m.%Y'), header_value)],
            [Paragraph("MANZIL:", header_label), Paragraph(project.address or "-", header_value),
             Paragraph("DAVR:", header_label), Paragraph(period_label, header_value)]
        ]
        t_info = Table(info_data, colWidths=[60, 200, 60, 150])
        t_info.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))
        elements.append(t_info)
        elements.append(Spacer(1, 20))

        # --- Data Calculation ---
        incomes, materials, services = self._get_report_data(project, date_from, date_to)
        
        total_income = sum(incomes.mapped('amount'))
        total_material = sum(materials.mapped('total_cost'))
        total_service = sum(services.mapped('total_cost'))
        total_expense = total_material + total_service
        balance = total_income - total_expense

        # --- Summary Cards ---
        summary_data = [[
            [Paragraph("KIRIM", card_label), Paragraph(f"+{total_income:,.0f}", card_value_income)],
            [Paragraph("XARAJAT", card_label), Paragraph(f"{total_expense:,.0f}", card_value_expense)],
            [Paragraph("BALANS", card_label), Paragraph(f"{balance:,.0f}", card_value_balance)]
        ]]
        t_summary = Table(summary_data, colWidths=[170, 170, 170])
        t_summary.setStyle(TableStyle([
            ('BOX', (0,0), (0,0), 1, colors.HexColor('#E0E0E0')),
            ('BOX', (1,0), (1,0), 1, colors.HexColor('#E0E0E0')),
            ('BOX', (2,0), (2,0), 1, colors.HexColor('#E0E0E0')),
            ('BACKGROUND', (0,0), (2,0), colors.HexColor('#FAFAFA')),
            ('TOPPADDING', (0,0), (-1,-1), 15),
            ('BOTTOMPADDING', (0,0), (-1,-1), 15),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        elements.append(t_summary)
        elements.append(Spacer(1, 10))
        
        # Progress Bar Simulation (Budget vs Spent if we had budget, but for now just visual separator)
        # elements.append(Spacer(1, 10))
        
        # --- Breakdown By Category ---
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Xarajatlar Tuzilmasi", styles['Heading2']))
        
        breakdown_data = [
            ['Kategoriya', 'Summa', '% Ulush'],
            ['Materiallar', f"{total_material:,.0f}", f"{(total_material/total_expense*100) if total_expense else 0:.1f}%"],
            ['Xizmatlar', f"{total_service:,.0f}", f"{(total_service/total_expense*100) if total_expense else 0:.1f}%"],
            ['Jami', f"{total_expense:,.0f}", "100%"]
        ]
        t_breakdown = Table(breakdown_data, colWidths=[200, 150, 100])
        t_breakdown.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2C3E50')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'), # Money right aligned
            ('ALIGN', (2,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 10),
            ('TOPPADDING', (0,0), (-1,0), 10),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8F9F9')]), # Alternating
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'), # Total row bold
        ]))
        elements.append(t_breakdown)
        elements.append(Spacer(1, 30))

        # --- Detailed Transaction List ---
        elements.append(Paragraph("Batafsil Operatsiyalar", styles['Heading2']))
        
        # Combine and Sort Data
        combined = []
        for i in incomes: 
            desc = i.description if i.description and str(i.description).lower() != 'false' else "Kirim"
            combined.append({'date': i.date, 'type': 'Kirim', 'name': desc, 'amount': i.amount, 'is_income': True})
            
        for m in materials: 
            combined.append({'date': m.date, 'type': 'Material', 'name': m.product_id.name, 'amount': -m.total_cost, 'is_income': False})
            
        for s in services: 
            combined.append({'date': s.date, 'type': 'Xizmat', 'name': s.service_id.name, 'amount': -s.total_cost, 'is_income': False})
        
        combined.sort(key=lambda x: x['date'], reverse=True)
        
        # Table Header
        detail_data = [['Sana', 'Turi', 'Nomi', 'Summa']]
        
        row_colors = []
        
        for idx, row in enumerate(combined):
            # Format Amount
            amt_str = f"{row['amount']:,.0f}"
            if row['is_income']:
                amt_str = f"+{amt_str}"
                
            # Date format
            date_str = row['date'].strftime('%d.%m.%Y') if row['date'] else "-"
            
            detail_data.append([
                date_str,
                row['type'],
                Paragraph(row['name'], styles['Normal']), # Wrap long text
                amt_str
            ])
            
            # Color logic for amount column
            if row['is_income']:
                row_colors.append(('TEXTCOLOR', (3, idx+1), (3, idx+1), colors.HexColor('#27AE60'))) # Green
            else:
                row_colors.append(('TEXTCOLOR', (3, idx+1), (3, idx+1), colors.HexColor('#C0392B'))) # Red

        t_detail = Table(detail_data, colWidths=[80, 80, 250, 100], repeatRows=1)
        
        detail_style = [
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#95A5A6')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ALIGN', (3,0), (-1,-1), 'RIGHT'), # Amount right aligned
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F4F6F6')]),
        ]
        detail_style.extend(row_colors) # Add dynamic colors
        
        t_detail.setStyle(TableStyle(detail_style))
        elements.append(t_detail)
        
        doc.build(elements)
        return buffer.getvalue()

    def _generate_excel_report(self, project, date_from, date_to, period_label):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet(f"Hisobot")
        
        # --- Formats ---
        
        # Header
        fmt_title = workbook.add_format({
            'bold': True, 'font_size': 20, 'font_color': '#2C3E50', 
            'align': 'left', 'valign': 'vcenter'
        })
        fmt_subtitle = workbook.add_format({
            'font_size': 12, 'font_color': '#7F8C8D', 
            'align': 'left', 'valign': 'vcenter'
        })
        
        # Dashboard Cards
        fmt_card_label = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'font_color': '#7F8C8D', 
            'border': 1, 'bg_color': '#FAFAFA'
        })
        fmt_card_val_inc = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#27AE60', 
            'align': 'center', 'valign': 'vcenter', 'num_format': '+#,##0',
            'border': 1, 'bg_color': '#FAFAFA'
        })
        fmt_card_val_exp = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#C0392B', 
            'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0',
            'border': 1, 'bg_color': '#FAFAFA'
        })
        fmt_card_val_bal = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#2980B9', 
            'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0',
            'border': 1, 'bg_color': '#FAFAFA'
        })

        # Table Headers
        fmt_th = workbook.add_format({
            'bold': True, 'bg_color': '#2C3E50', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        
        # Table Content
        fmt_date = workbook.add_format({
            'num_format': 'dd.mm.yyyy', 'border': 1, 'align': 'center'
        })
        fmt_text = workbook.add_format({'border': 1})
        fmt_text_center = workbook.add_format({'border': 1, 'align': 'center'})
        
        fmt_money_inc = workbook.add_format({
            'num_format': '+#,##0', 'font_color': '#27AE60', 'border': 1
        })
        fmt_money_exp = workbook.add_format({
            'num_format': '-#,##0', 'font_color': '#C0392B', 'border': 1
        })
        
        # --- Column Sizes ---
        worksheet.set_column('A:A', 15) # Sana
        worksheet.set_column('B:B', 15) # Turi
        worksheet.set_column('C:C', 40) # Nomi
        worksheet.set_column('D:D', 20) # Bosqich
        worksheet.set_column('E:E', 15) # Status
        worksheet.set_column('F:F', 20) # Summa

        # --- Header Section ---
        worksheet.write('A1', f"{project.name}", fmt_title)
        worksheet.write('A2', f"Mijoz: {project.customer_id.name} | Davr: {period_label}", fmt_subtitle)
        worksheet.write('F1', f"Sana: {date.today().strftime('%d.%m.%Y')}", fmt_subtitle)

        # --- Calculations ---
        incomes, materials, services = self._get_report_data(project, date_from, date_to)
        
        total_income = sum(incomes.mapped('amount'))
        total_material = sum(materials.mapped('total_cost'))
        total_service = sum(services.mapped('total_cost'))
        total_expense = total_material + total_service
        balance = total_income - total_expense

        # --- Dashboard (Rows 4-5) ---
        # Kirim
        worksheet.merge_range('A4:B4', "JAMI KIRIM", fmt_card_label)
        worksheet.merge_range('A5:B5', total_income, fmt_card_val_inc)
        
        # Chiqim
        worksheet.merge_range('C4:D4', "JAMI XARAJAT", fmt_card_label)
        worksheet.merge_range('C5:D5', total_expense, fmt_card_val_exp)
        
        # Balans
        worksheet.merge_range('E4:F4', "BALANS", fmt_card_label)
        worksheet.merge_range('E5:F5', balance, fmt_card_val_bal)
        
        # --- Breakdown (Rows 7-10) ---
        worksheet.write('A7', "Xarajatlar Tuzilmasi", fmt_subtitle)
        worksheet.write_row('A8', ['Kategoriya', 'Summa'], fmt_th)
        
        worksheet.write('A9', 'Materiallar', fmt_text)
        worksheet.write('B9', total_material, fmt_card_val_exp)
        
        worksheet.write('A10', 'Xizmatlar', fmt_text)
        worksheet.write('B10', total_service, fmt_card_val_exp)
        
        # --- Detailed List (Row 12+) ---
        worksheet.write('A12', "Batafsil Operatsiyalar", fmt_subtitle)
        
        headers = ['Sana', 'Turi', 'Nomi', 'Bosqich', 'Holat', 'Summa']
        worksheet.write_row('A13', headers, fmt_th)
        
        start_row = 13
        
        # Combine Data
        rows = []
        status_map = {
            'draft': 'Qoralama', 'pending': 'Kutilmoqda', 'approved': 'Tasdiqlandi',
            'done': 'Bajarildi', 'paid': "To'landi", 'cancel': 'Bekor qilindi',
            'process': 'Jarayonda', 'new': 'Yangi'
        }
        
        for i in incomes:
            desc = i.description or "Kirim"
            if str(desc).lower() == 'false': desc = "Kirim"
            rows.append({
                'date': i.date, 'type': 'Kirim', 'name': desc, 
                'stage': '-', 'status': 'Tasdiqlandi', 
                'amount': i.amount, 'is_income': True
            })
            
        for m in materials:
            st = status_map.get(m.state, m.state)
            rows.append({
                'date': m.date, 'type': 'Material', 'name': m.product_id.name, 
                'stage': m.stage_id.name, 'status': st, 
                'amount': m.total_cost, 'is_income': False
            })
            
        for s in services:
            st = 'Bajarildi' if s.is_done else 'Reja'
            rows.append({
                'date': s.date, 'type': 'Xizmat', 'name': s.service_id.name, 
                'stage': s.stage_id.name, 'status': st, 
                'amount': s.total_cost, 'is_income': False
            })
            
        rows.sort(key=lambda x: x['date'], reverse=True)
        
        for i, row in enumerate(rows):
            r = start_row + i
            worksheet.write(r, 0, row['date'], fmt_date)
            worksheet.write(r, 1, row['type'], fmt_text_center)
            worksheet.write(r, 2, row['name'], fmt_text)
            worksheet.write(r, 3, row['stage'], fmt_text)
            worksheet.write(r, 4, row['status'], fmt_text_center)
            
            if row['is_income']:
                worksheet.write(r, 5, row['amount'], fmt_money_inc)
            else:
                worksheet.write(r, 5, row['amount'], fmt_money_exp)
        
        workbook.close()
        return output.getvalue()

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

class ConstructionCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super(ConstructionCustomerPortal, self)._prepare_home_portal_values(counters)
        if 'construction_count' in counters:
            partner = request.env.user.partner_id
            values['construction_count'] = request.env['construction.project'].search_count([
                ('customer_id', '=', partner.id)
            ])
        return values

    @http.route(['/my/construction/projects', '/my/construction/projects/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_construction_projects(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        ConstructionProject = request.env['construction.project']

        domain = [('customer_id', '=', partner.id)]

        searchbar_sortings = {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'name'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Count for pager
        construction_count = ConstructionProject.search_count(domain)
        
        # Pager
        pager = portal_pager(
            url="/my/construction/projects",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=construction_count,
            page=page,
            step=self._items_per_page
        )

        projects = ConstructionProject.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_construction_history'] = projects.ids[:100]

        values.update({
            'date': date_begin,
            'projects': projects,
            'page_name': 'construction_project',
            'default_url': '/my/construction/projects',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby
        })
        return request.render("construction_management.portal_my_projects", values)

    @http.route(['/my/construction/project/<int:project_id>'], type='http', auth="user", website=True)
    def portal_my_project_detail(self, project_id, access_token=None, **kw):
        try:
            project_sudo = self._document_check_access('construction.project', project_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Ensure security check for customer_id matches current user's partner
        # _document_check_access usually relies on record rules, but we want extra safety if record rules are loose
        partner = request.env.user.partner_id
        if project_sudo.customer_id.id != partner.id:
             return request.redirect('/my')

        values = self._get_page_view_values(project_sudo, access_token, **kw)
        
        # Precompute breakdown for template to avoid heavy logic in qweb
        # Structure:
        # stages_data = [
        #    {
        #       'stage': stage_record,
        #       'materials': [mat1, mat2...],
        #       'services': [svc1, svc2...],
        #       'images': [img1, img2...],
        #       'stage_total': float
        #    }
        # ]
        
        stages_data = []
        for stage in project_sudo.stage_ids:
            materials = request.env['construction.stage.material'].search([('stage_id', '=', stage.id)])
            services = request.env['construction.stage.service'].search([('stage_id', '=', stage.id)])
            images = request.env['construction.stage.image'].search([('stage_id', '=', stage.id)])
            
            stage_mat_total = sum(m.total_price for m in materials)
            stage_svc_total = sum(s.total_price for s in services)
            
            stages_data.append({
                'stage': stage,
                'materials': materials,
                'services': services,
                'images': images,
                'stage_total': stage_mat_total + stage_svc_total
            })

        values.update({
            'stages_data': stages_data,
            'page_name': 'construction_project',
        })
        
        return request.render("construction_management.portal_construction_report", values)

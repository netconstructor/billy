from __future__ import unicode_literals

import transaction as db_transaction
from pyramid.view import view_config
from pyramid.security import authenticated_userid
from pyramid.httpexceptions import HTTPForbidden
from pyramid.httpexceptions import HTTPBadRequest

from billy.models.invoice import InvoiceModel
from billy.models.transaction import TransactionModel
from billy.api.utils import validate_form
from billy.api.utils import list_by_context
from billy.api.resources import IndexResource
from billy.api.resources import EntityResource
from billy.api.views import IndexView
from billy.api.views import EntityView
from billy.api.views import api_view_defaults
from .forms import InvoiceCreateForm
from .forms import InvoiceUpdateForm
from .forms import InvoiceRefundForm


def parse_items(request, prefix, keywords):
    """This function parsed items from request in following form

        item_name1=a
        item_amount1=100
        item_name2=b
        item_amount2=999
        item_unit2=hours
        item_name3=foo
        item_amount3=123

    and return a list as [
        dict(title='a', amount='100'),
        dict(title='b', amount='999', unit='hours'),
        dict(title='foo', amount='123'),
    ]

    """
    # TODO: humm.. maybe it is not the best method to deals with multiple
    # value parameters, but here we just make it works and make it better
    # later
    # TODO: what about format checking? length limitation? is amount integer?
    items = {}
    for key in request.params:
        for keyword in keywords:
            prefixed_keyword = prefix + keyword
            suffix = key[len(prefixed_keyword):]
            if not key.startswith(prefixed_keyword):
                continue
            try:
                item_num = int(suffix)
            except ValueError:
                continue
            item = items.setdefault(item_num, {})
            item[keyword] = request.params[key]
    keys = list(items)
    keys = sorted(keys)
    return [items[key] for key in keys]


class InvoiceResource(EntityResource):
    @property
    def company(self):
        return self.entity.customer.company


class InvoiceIndexResource(IndexResource):
    MODEL_CLS = InvoiceModel
    ENTITY_NAME = 'invoice'
    ENTITY_RESOURCE = InvoiceResource


@api_view_defaults(context=InvoiceIndexResource)
class InvoiceIndexView(IndexView):

    @view_config(request_method='GET', permission='view')
    def get(self):
        request = self.request
        company = authenticated_userid(request)
        return list_by_context(request, InvoiceModel, company)

    @view_config(request_method='POST', permission='create')
    def post(self):
        request = self.request

        form = validate_form(InvoiceCreateForm, request)
        model = request.model_factory.create_invoice_model()
        customer_model = request.model_factory.create_customer_model()
        tx_model = request.model_factory.create_transaction_model()
        company = authenticated_userid(request)
       
        customer_guid = form.data['customer_guid']
        amount = form.data['amount']
        funding_instrument_uri = form.data.get('funding_instrument_uri')
        if not funding_instrument_uri:
            funding_instrument_uri = None
        title = form.data.get('title')
        if not title:
            title = None
        external_id = form.data.get('external_id')
        if not external_id:
            external_id = None
        appears_on_statement_as = form.data.get('appears_on_statement_as')
        if not appears_on_statement_as:
            appears_on_statement_as = None
        items = parse_items(
            request=request,
            prefix='item_',
            keywords=('type', 'name', 'volume', 'amount', 'unit', 'quantity'),
        )
        if not items:
            items = None
        adjustments = parse_items(
            request=request,
            prefix='adjustment_',
            keywords=('amount', 'reason'),
        )
        if not adjustments:
            adjustments = None
        # TODO: what about negative effective amount?

        customer = customer_model.get(customer_guid)
        if customer.company != company:
            return HTTPForbidden('Can only create an invoice for your own customer')
        if customer.deleted:
            return HTTPBadRequest('Cannot create an invoice for a deleted customer')
       
        # Notice: I think it is better to validate the funding instrument URI
        # even before the record is created. Otherwse, the user can only knows
        # what's wrong after we try to submit it to the underlying processor.
        # (he can read the transaction failure log and eventually realize
        # the processing was failed)
        # The idea here is to advance error as early as possible.
        if funding_instrument_uri is not None:
            processor = request.model_factory.create_processor()
            processor.configure_api_key(customer.company.processor_key)
            processor.validate_funding_instrument(funding_instrument_uri)

        with db_transaction.manager:
            invoice = model.create(
                customer=customer,
                amount=amount,
                funding_instrument_uri=funding_instrument_uri,
                title=title,
                items=items,
                adjustments=adjustments,
                external_id=external_id,
                appears_on_statement_as=appears_on_statement_as,
            )
        # funding_instrument_uri is set, just process all transactions right away
        if funding_instrument_uri is not None:
            transactions = list(invoice.transactions)
            if transactions:
                with db_transaction.manager:
                    tx_model.process_transactions(transactions)
        return invoice


@api_view_defaults(context=InvoiceResource)
class InvoiceView(EntityView):

    @view_config(request_method='GET')
    def get(self):
        return self.context.entity

    @view_config(request_method='PUT')
    def put(self):
        request = self.request

        invoice = self.context.entity
        form = validate_form(InvoiceUpdateForm, request)
        model = request.model_factory.create_invoice_model()
        tx_model = request.model_factory.create_transaction_model()

        funding_instrument_uri = form.data.get('funding_instrument_uri')
       
        with db_transaction.manager:
            transactions = model.update_funding_instrument_uri(
                invoice=invoice,
                funding_instrument_uri=funding_instrument_uri,
            )

        # funding_instrument_uri is set, just process all transactions right away
        if funding_instrument_uri and transactions:
            with db_transaction.manager:
                tx_model.process_transactions(transactions)

        return invoice

    @view_config(name='refund', request_method='POST')
    def refund(self):
        """Issue a refund to customer

        """
        request = self.request
        invoice = self.context.entity
        form = validate_form(InvoiceRefundForm, request)
        invoice_model = request.model_factory.create_invoice_model()
        tx_model = request.model_factory.create_transaction_model()

        amount = form.data['amount']

        with db_transaction.manager:
            transactions = invoice_model.refund(
                invoice=invoice,
                amount=amount,
            )

        # funding_instrument_uri is set, just process all transactions right away
        if transactions:
            with db_transaction.manager:
                tx_model.process_transactions(transactions)
        return invoice

    @view_config(name='cancel', request_method='POST')
    def cancel(self):
        """Cancel the invoice

        """
        request = self.request
        invoice = self.context.entity
        invoice_model = request.model_factory.create_invoice_model()

        with db_transaction.manager:
            invoice_model.cancel(invoice=invoice)
        return invoice

    @view_config(name='transactions')
    def transaction_index(self):
        """Get and return the list of transactions unrder current customer

        """
        return list_by_context(
            self.request,
            TransactionModel,
            self.context.entity,
        )

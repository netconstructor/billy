from __future__ import unicode_literals

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy.schema import ForeignKey
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship

from .base import DeclarativeBase
from .base import UTCDateTime
from .base import now_func
from ..enum import DeclEnum


class TransactionType(DeclEnum):

    DEBIT = 'DEBIT', 'Debit'
    CREDIT = 'CREDIT', 'Credit'
    REFUND = 'REFUND', 'Refund'
    REVERSE = 'REVERSE', 'Reverse'


class TransactionSubmitStatus(DeclEnum):

    STAGED = 'STAGED', 'Staged'
    RETRYING = 'RETRYING', 'Retrying'
    DONE = 'DONE', 'Done'
    FAILED = 'FAILED', 'Failed'
    CANCELED = 'CANCELED', 'Canceled'


class TransactionStatus(DeclEnum):

    PENDING = 'PENDING', 'Pending'
    SUCCEEDED = 'SUCCEEDED', 'Succeeded'
    FAILED = 'FAILED', 'Failed'


class Transaction(DeclarativeBase):
    """A transaction reflects a debit/credit/refund/reversal in payment
    processing system

    """
    __tablename__ = 'transaction'

    guid = Column(Unicode(64), primary_key=True)
    #: the guid of invoice which owns this transaction
    invoice_guid = Column(
        Unicode(64),
        ForeignKey(
            'invoice.guid',
            ondelete='CASCADE', onupdate='CASCADE'
        ),
        index=True,
        nullable=False,
    )
    #: the guid of target transaction to refund/reverse to
    reference_to_guid = Column(
        Unicode(64),
        ForeignKey(
            'transaction.guid',
            ondelete='CASCADE', onupdate='CASCADE'
        ),
        index=True,
    )
    #: what type of transaction it is, could be DEBIT, CREDIT, REFUND or REVERSE
    transaction_type = Column(TransactionType.db_type(), index=True, nullable=False)
    #: the URI of transaction record in payment processing system
    processor_uri = Column(Unicode(128), index=True)
    #: the statement to appear on customer's transaction record (either
    #  bank account or credit card)
    appears_on_statement_as = Column(Unicode(32))
    #: current submition status of this transaction
    submit_status = Column(TransactionSubmitStatus.db_type(), index=True,
                           nullable=False)
    #: current status in underlying payment processor
    status = Column(TransactionStatus.db_type(), index=True)
    #: the amount to do transaction (charge, payout or refund)
    amount = Column(Integer, nullable=False)
    #: the funding instrument URI
    funding_instrument_uri = Column(Unicode(128), index=True)
    #: the created datetime of this transaction
    created_at = Column(UTCDateTime, default=now_func)
    #: the updated datetime of this transaction
    updated_at = Column(UTCDateTime, default=now_func)

    #: target transaction of refund/reverse transaction
    reference_to = relationship(
        'Transaction',
        cascade='all, delete-orphan',
        backref=backref('reference_from', uselist=False),
        remote_side=[guid],
        uselist=False,
        single_parent=True,
    )

    #: transaction events
    events = relationship(
        'TransactionEvent',
        cascade='all, delete-orphan',
        backref='transaction',
        # new events first
        order_by='TransactionEvent.occurred_at.desc(),TransactionEvent.processor_id.desc()',
        lazy='dynamic',  # so that we can query on it
    )

    #: transaction failures
    failures = relationship(
        'TransactionFailure',
        cascade='all, delete-orphan',
        backref='transaction',
        order_by='TransactionFailure.created_at',
        lazy='dynamic',  # so that we can query count on it
    )

    @property
    def failure_count(self):
        """Count of failures

        """
        return self.failures.count()

    @property
    def company(self):
        """Owner company of this transaction

        """
        from .invoice import InvoiceType
        if self.invoice.invoice_type == InvoiceType.SUBSCRIPTION:
            company = self.invoice.subscription.plan.company
        else:
            company = self.invoice.customer.company
        return company


class TransactionEvent(DeclarativeBase):
    """A transaction event is a record which indicates status change of
    transaction

    """
    __tablename__ = 'transaction_event'
    # ensure one event will only appear once in this transaction
    __table_args__ = (UniqueConstraint('transaction_guid', 'processor_id'), )

    guid = Column(Unicode(64), primary_key=True)
    #: the guid of transaction which owns this event
    transaction_guid = Column(
        Unicode(64),
        ForeignKey(
            'transaction.guid',
            ondelete='CASCADE', onupdate='CASCADE'
        ),
        index=True,
        nullable=False,
    )
    #: the id of event record in payment processing system
    # Notice: why not use URI, because there are many variants of URI
    # to the same event resource, we want to ensure the same event
    # will only appear once. Otherwise, attacker could fool Billy system
    # by the same event with different URI
    processor_id = Column(Unicode(128), index=True, nullable=False)
    #: current status in underlying payment processor
    status = Column(TransactionStatus.db_type(), index=True, nullable=False)
    #: occurred datetime of this event
    # (this dt is from Balanced API service, not generated in Billy)
    occurred_at = Column(UTCDateTime, index=True, nullable=False)
    #: created datetime of this event
    created_at = Column(UTCDateTime, default=now_func)


class TransactionFailure(DeclarativeBase):
    """A failure of transaction

    """
    __tablename__ = 'transaction_failure'

    guid = Column(Unicode(64), primary_key=True)

    #: the guid of transaction which owns this failure
    transaction_guid = Column(
        Unicode(64),
        ForeignKey(
            'transaction.guid',
            ondelete='CASCADE', onupdate='CASCADE'
        ),
        index=True,
        nullable=False,
    )

    #: error message when failed
    error_message = Column(UnicodeText)
    #: error number
    error_number = Column(Integer)
    #: error code
    error_code = Column(Unicode(64))
    #: the created datetime of this failure
    created_at = Column(UTCDateTime, default=now_func)

__all__ = [
    TransactionType.__name__,
    TransactionSubmitStatus.__name__,
    TransactionStatus.__name__,
    Transaction.__name__,
    TransactionEvent.__name__,
    TransactionFailure.__name__,
]

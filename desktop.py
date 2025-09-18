from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_

# Import the Ticket model from your models module
from .models import Ticket  # Use relative import if models.py is in the same directory

# Business hours: Monday-Friday, 9 AM - 6 PM (9 hours per day)
def add_business_hours(start_time: datetime, hours: float) -> datetime:
    business_hours_per_day = 9
    current_time = start_time
    remaining_hours = hours

    while remaining_hours > 0:
        # Skip weekends
        if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            current_time += timedelta(days=1)
            current_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            continue

        # If outside business hours, move to next business day
        if current_time.hour < 9:
            current_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
        elif current_time.hour >= 18:
            current_time += timedelta(days=1)
            current_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            continue

        # Calculate hours remaining in current business day
        hours_left_today = 18 - current_time.hour - (current_time.minute / 60.0)

        if remaining_hours <= hours_left_today:
            # Can finish today
            current_time += timedelta(hours=remaining_hours)
            remaining_hours = 0
        else:
            # Need to continue tomorrow
            remaining_hours -= hours_left_today
            current_time += timedelta(days=1)
            current_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)

    return current_time

class SLAService:
    def check_sla_breaches(self, db: Session) -> List[Dict]:
        '''Check for current SLA breaches'''

        current_time = datetime.utcnow()
        breached_tickets = []

        # Find tickets with breached first response SLA
        first_response_breaches = db.query(Ticket).filter(
            and_(
                Ticket.first_response_due < current_time,
                Ticket.first_response_at.is_(None),
                Ticket.status != 'closed'
            )
        ).all()

        for ticket in first_response_breaches:
            breach_time = current_time - ticket.first_response_due
            breached_tickets.append({
                'ticket_id': ticket.id,
                'breach_type': 'first_response',
                'breach_duration': str(breach_time),
                'priority': ticket.priority,
                'customer_tier': ticket.customer.tier if ticket.customer else 'standard'
            })

        # Find tickets with breached resolution SLA
        resolution_breaches = db.query(Ticket).filter(
            and_(
                Ticket.resolution_due < current_time,
                Ticket.resolved_at.is_(None),
                Ticket.status != 'closed'
            )
        ).all()

        for ticket in resolution_breaches:
            breach_time = current_time - ticket.resolution_due
            breached_tickets.append({
                'ticket_id': ticket.id,
                'breach_type': 'resolution',
                'breach_duration': str(breach_time),
                'priority': ticket.priority,
                'customer_tier': ticket.customer.tier if ticket.customer else 'standard'
            })

        return breached_tickets

    def generate_sla_report(self, db: Session, start_date: datetime, end_date: datetime, category: str = None) -> Dict:
        '''Generate comprehensive SLA performance report'''

        query = db.query(Ticket).filter(
            and_(
                Ticket.created_at >= start_date,
                Ticket.created_at <= end_date
            )
        )

        if category:
            query = query.filter(Ticket.category == category)

        tickets = query.all()

        # Calculate SLA metrics
        total_tickets = len(tickets)
        first_response_met = 0
        resolution_met = 0
        avg_first_response_time = 0
        avg_resolution_time = 0

        first_response_times = []
        resolution_times = []

        for ticket in tickets:
            # First response SLA
            if ticket.first_response_at:
                response_time = (ticket.first_response_at - ticket.created_at).total_seconds() / 3600
                first_response_times.append(response_time)

                if ticket.first_response_at <= ticket.first_response_due:
                    first_response_met += 1

            # Resolution SLA
            if ticket.resolved_at:
                resolution_time = (ticket.resolved_at - ticket.created_at).total_seconds() / 3600
                resolution_times.append(resolution_time)

                if ticket.resolved_at <= ticket.resolution_due:
                    resolution_met += 1

        # Calculate averages
        if first_response_times:
            avg_first_response_time = sum(first_response_times) / len(first_response_times)

        if resolution_times:
            avg_resolution_time = sum(resolution_times) / len(resolution_times)

        # SLA compliance percentages
        first_response_compliance = (first_response_met / total_tickets * 100) if total_tickets > 0 else 0
        resolution_compliance = (resolution_met / total_tickets * 100) if total_tickets > 0 else 0

        return {
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'total_tickets': total_tickets,
            'first_response_sla': {
                'compliance_rate': round(first_response_compliance, 2),
                'tickets_met': first_response_met,
                'avg_response_time_hours': round(avg_first_response_time, 2)
            },
            'resolution_sla': {
                'compliance_rate': round(resolution_compliance, 2),
                'tickets_met': resolution_met,
                'avg_resolution_time_hours': round(avg_resolution_time, 2)
            }
        }
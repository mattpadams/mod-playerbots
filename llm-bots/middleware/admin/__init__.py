"""Admin service layer.

Orchestrates repositories + external systems (SOAP, game DB) on behalf
of the admin API + dashboard. Services own business rules; repos own
persistence; routes own HTTP concerns.
"""

# -*- coding: utf-8 -*-
"""Pausa adaptativa: 10s tras éxito confirmado; 30s mínimo en error.

La limitación Microsoft 429 permanece global y no se reintenta automáticamente.
"""
def completed_mailbox(phase,rate_limited=False,blocked=False,extra_verification=False,password_unavailable=False):
    return (phase == 'mail' and not any((rate_limited,blocked,extra_verification,password_unavailable)))

def interval_seconds(successful):
    return 10 if successful else 30

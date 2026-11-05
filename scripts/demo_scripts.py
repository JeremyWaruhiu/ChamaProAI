"""The demo's exact answers, for warm_demo.py and tests/latency_demo.py: what each person says,
and which lines the bot should answer with. Njeri gives no term with her request, so she hears C1."""
SCRIPTS = {
    ("Wanjiru Kamau", "en"): [("Yes, I agree", ["G2"]), ("Yes, that is correct", ["R1"]),
                              ("Forty thousand for a dairy cow", ["C1"]), ("Twelve months", ["CONFIRM"]),
                              ("Yes, go ahead", ["O1", "END"])],
    ("Wanjiru Kamau", "kik"): [("Ĩĩ", ["G2"]), ("Nĩ guo", ["R1"]), ("Ngũkwenda ngiri mĩrongo ĩna ngũre ng'ombe", ["C1"]),
                               ("Mĩeri ikũmi na igĩrĩ", ["CONFIRM"]), ("Ĩĩ", ["O1", "END"])],
    ("Njeri Mwangi", "en"): [("Yes, I agree", ["G2_NO_INCOME"]), ("Yes, that is correct", ["R1"]),
                             ("Sixty thousand for school fees", ["C1"]), ("Twelve months", ["C2"]),
                             ("No, it is twenty two thousand now", ["CONFIRM"]), ("Yes, go ahead", ["O2", "END"])],
    ("Njeri Mwangi", "kik"): [("Ĩĩ", ["G2_NO_INCOME"]), ("Nĩ guo", ["R1"]),
                              ("Ngũkwenda ngiri mĩrongo ĩtandatũ cia cukuru", ["C1"]), ("Mĩeri ikũmi na igĩrĩ", ["C2"]),
                              ("Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ", ["CONFIRM"]), ("Ĩĩ", ["O2", "END"])],
}

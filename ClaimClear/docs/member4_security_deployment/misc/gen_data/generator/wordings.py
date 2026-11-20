"""Policy wordings the generator supports. One entry per wording.

To add a wording: put its PDF in data/policy/arogya-sanjeevani/, copy the IFFCO entry below, change the
figures and clause numbers after checking each one against the PDF, and set "wording": "<KEY>" in a recipe.
Each case folder gets a copy of its wording PDF as 00_policy_wording.pdf.

Waiting-period classes used by generator/profiles.py:
  list_i  = the shorter specific-waiting list (hernia, cataract, calculi, hysterectomy, ...)
  list_ii = the longer list (joint replacement, age-related osteoarthritis/osteoporosis)
"""

WORDINGS = {
    "IFFCO": {
        "title": "Arogya Sanjeevani Policy - Policy Wording",
        "uin": "IFFHLIP20161V011920",
        "pdf": "data/policy/arogya-sanjeevani/AS_iffco_tokio_policy_wording.pdf",
        # One fixed fictional insurer per wording, so a name always means the same wording.
        # Code starts with X so the UIN cannot match a real insurer prefix.
        "insurer": {"name": "Narmada Health & General Insurance Ltd.", "short": "NHGI", "code": "XNH",
                    "domain": "narmada-hgi.example", "addr1": "Narmada Bhawan, Block B",
                    "addr2": "Arera Hills, Bhopal - 462000", "toll": "1800-000-0301", "toll_sr": "1800-000-0302"},
        "room_pct": 2, "room_max": 5000, "icu_pct": 5, "icu_max": 10000,
        "cataract_pct": 25, "cataract_max": 40000, "modern_pct": 50, "ambulance_max": 2000,
        "copay_pct": 5, "wait_first_days": 30, "ped_months": 36,
        "wait_months": {"list_i": 24, "list_ii": 48},
        # Identifying text swapped for the case's fictional insurer in the copy put in each case folder.
        # Longest strings first. Everything else in the wording is copied word for word.
        "rebrand": [
            ("IFFCO-Tokio General Insurance Company Limited", "{name}"),
            ("IFFCO-Tokio General Insurance Co Ltd", "{name}"),
            ("https://www.iffcotokio.co.in/customer-services/grievance-redressal", "https://www.{domain}/grievance"),
            ("www.iffcotokio.co.in", "www.{domain}"),
            ("@iffcotokio.co.in", "@{domain}"),
            ("IFFCO Tower, Plot no. 3", "{addr1}"),
            ("Sector -29, Gurgaon – 122001", "{addr2}"),
            ("1800-103-5499", "{toll}"),
            ("1800-103-5498", "{toll_sr}"),
            ("IFFHLIP20161V011920", "{uin}"),
            ("ITGI", "{short}"),
            ("IFFCO-Tokio", "{short}"),
        ],
        "residue": r"iffco|tokio|itgi|iffhlip",  # build fails if any of these survive
        "clause": {
            "room": "4.1(i)", "icu": "4.1(ii)", "prop": "4.1 Note 2", "nonpay": "4.7, Annexure A",
            "ambulance": "4.1.1(v)", "cataract": "4.3", "modern": "4.6", "copay": "9.3", "si": "2, 3.47",
            "wait30": "6.2", "wait_spec": "6.3", "ped": "6.1", "min24": "4.1 Note 1",
            "pre": "4.4", "post": "4.5", "period": "2 (Operative clause)",
        },
    },
    # "NIA": New India 2024-25 wording (NIAHLIP25044V022425). Same figures except list_ii = 36 months;
    # clauses: room 4.1(a), icu 4.1(b), prop 4.1 Note b, ambulance 4.1.1(e), copay 9.5, wait30 6.3,
    # wait_spec 6.2. Not enabled yet: check against the PDF before adding.
}

DEFAULT_WORDING = "IFFCO"

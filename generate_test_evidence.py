#!/usr/bin/env python3
"""
Generate a ~200 MB synthetic digital-evidence text file for testing
the Intelligent Digital Forensic AI Assistant ingestion pipeline.
"""

import random, hashlib, uuid, os, sys, time
from datetime import datetime, timedelta

TARGET_MB   = int(sys.argv[1]) if len(sys.argv) > 1 else 10
TARGET_BYTES = TARGET_MB * 1024 * 1024
OUT_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"test_evidence_{TARGET_MB}mb.txt")

SUSPECTS = [
    ("Marcus Blackwell",  "m.blackwell@vortexcorp.com",   "+1-202-555-0147"),
    ("Diana Sokolov",     "d.sokolov@vortexcorp.com",     "+1-415-555-0398"),
    ("James Okoro",       "j.okoro@vortexcorp.com",       "+44-20-7946-0958"),
    ("Priya Mehta",       "p.mehta@vortexcorp.com",       "+91-98765-43210"),
    ("Carlos Rivera",     "c.rivera@phantomlabs.net",     "+34-612-345-678"),
    ("Elena Vasquez",     "e.vasquez@phantomlabs.net",    "+1-305-555-0213"),
    ("Yuki Tanaka",       "y.tanaka@darknode.io",         "+81-90-1234-5678"),
    ("Aleksandr Petrov",  "a.petrov@darknode.io",         "+7-495-555-1234"),
    ("Fatima Al-Rashid",  "f.alrashid@securemail.org",   "+971-50-123-4567"),
    ("Nathan Cole",       "n.cole@vortexcorp.com",        "+1-312-555-0891"),
    ("Sophie Brennan",    "s.brennan@vortexcorp.com",     "+353-87-123-4567"),
    ("Wei Zhang",         "w.zhang@darknode.io",          "+86-138-0013-8000"),
]

CASE_IDS = ["IDF-2025-0042", "IDF-2025-0078", "IDF-2025-0113", "IDF-2025-0156", "IDF-2025-0201"]
CASE_NAMES = [
    "Operation Phantom Ledger - Corporate Embezzlement and Money Laundering",
    "Operation Dark Mirror - Insider Threat and IP Exfiltration",
    "Operation Silent Wire - Ransomware Attack and Data Breach",
    "Operation Ghost Market - Dark-Web Narcotics Trafficking",
    "Operation Iron Veil - State-Sponsored Cyber Espionage",
]

DOMAINS = [
    "vortexcorp.com", "phantomlabs.net", "darknode.io",
    "securemail.org", "protonmail.com", "tutanota.com",
    "offshore-bank.ky", "cryptovault.ch", "shell-holdings.pa",
    "safecomms.onion",
]

IPS = [
    "10.0.14.22", "10.0.14.55", "192.168.1.101", "192.168.1.204",
    "172.16.5.30", "172.16.5.88", "203.0.113.47", "198.51.100.19",
    "45.33.32.156", "91.198.174.192", "185.220.101.34", "104.21.56.78",
    "78.46.224.50", "5.199.130.188", "31.13.65.36",
]

CRYPTO_WALLETS = [
    "bc1q" + hashlib.sha256(str(i).encode()).hexdigest()[:38] for i in range(20)
]

FILE_PATHS_WIN = [
    "C:\\Users\\mblackwell\\Documents\\Q4_Financials_CONFIDENTIAL.xlsx",
    "C:\\Users\\mblackwell\\AppData\\Local\\Temp\\exfil_tool.exe",
    "C:\\Users\\dsokolov\\Desktop\\client_database_backup.sql",
    "C:\\Users\\dsokolov\\Downloads\\TOR-browser-installer.exe",
    "C:\\ProgramData\\VortexCorp\\HR\\employee_ssn_records.csv",
    "C:\\Users\\jokoro\\Documents\\merger_acquisition_plan_draft.docx",
    "C:\\Users\\jokoro\\AppData\\Roaming\\Signal\\databases\\signal.db",
    "C:\\Windows\\System32\\drivers\\rootkit_driver.sys",
    "D:\\Backup\\encrypted_archive_20250415.7z",
    "C:\\Users\\ncole\\Documents\\whistleblower_evidence.pdf",
]

FILE_PATHS_LINUX = [
    "/home/crivera/projects/malware_builder/payload.c",
    "/opt/phantomlabs/staging/exfiltrated_data.tar.gz",
    "/var/log/auth.log",
    "/tmp/.hidden/cryptominer",
    "/home/ytanaka/darknode/c2_server.py",
    "/etc/cron.d/persistence_backdoor",
    "/home/apetrov/tools/password_cracker.py",
    "/var/www/html/webshell.php",
]

BANKS = [
    "Cayman National Bank", "Credit Suisse AG", "Banque de Luxembourg",
    "HSBC Holdings", "First Caribbean International", "Banco Nacional de Panama",
    "Royal Bank of Scotland", "Deutsche Bank AG", "Barclays PLC",
]

CURRENCIES = ["USD", "EUR", "GBP", "CHF", "BTC", "ETH", "XMR"]

MALWARE_NAMES = [
    "BlackCat/ALPHV", "LockBit 3.0", "Conti", "REvil/Sodinokibi",
    "Emotet", "TrickBot", "Cobalt Strike Beacon", "Mimikatz",
    "BloodHound", "Metasploit Meterpreter", "DarkComet RAT",
]

HASH_ALGOS = ["MD5", "SHA-1", "SHA-256"]

def rand_dt(base_year=2025):
    return datetime(base_year, 1, 1) + timedelta(
        days=random.randint(0, 364), hours=random.randint(0, 23),
        minutes=random.randint(0, 59), seconds=random.randint(0, 59))

def fmt_dt(d):
    return d.strftime("%Y-%m-%d %H:%M:%S UTC")

def rand_hash():
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()

def rand_md5():
    return hashlib.md5(uuid.uuid4().bytes).hexdigest()

def rand_ip():
    return random.choice(IPS)

def rand_suspect():
    return random.choice(SUSPECTS)

def rand_case():
    i = random.randint(0, len(CASE_IDS)-1)
    return CASE_IDS[i], CASE_NAMES[i]

EMAIL_SUBJECTS = [
    "Re: Quarterly projections - CONFIDENTIAL",
    "Fwd: Wire transfer confirmation",
    "URGENT: Delete all files before audit",
    "Meeting notes - Project Nightfall",
    "Invoice - Consulting Services",
    "Re: Offshore account setup - action required",
    "Fwd: Encrypted file password",
    "Due diligence report - Acquisition Target Alpha",
    "Re: Are we still on for tonight?",
    "IMPORTANT: Security breach detected",
    "Re: Employee termination - HR action",
    "New vendor onboarding",
    "Fwd: Cryptocurrency wallet details",
    "Re: Cover story for the auditors",
    "Travel reimbursement - suspicious entries",
    "Re: The shipment has arrived",
    "Fwd: Access credentials for staging server",
    "CONFIDENTIAL: Board meeting minutes",
    "Re: Need to move the money before Friday",
    "Alert: Unusual login activity detected",
]

def gen_email():
    sender = rand_suspect()
    recip  = rand_suspect()
    while recip == sender:
        recip = rand_suspect()
    dt = rand_dt()
    ref = str(random.randint(100000, 999999))
    subj = random.choice(EMAIL_SUBJECTS)

    body_templates = [
        lambda: (
            "Hi " + recip[0].split()[0] + ",\n\n"
            "As discussed in our last meeting, I have prepared the revised financial projections for Q4.\n"
            "The numbers look good on the surface, but I have buried the discrepancy in the consulting\n"
            "fees line item - approximately $" + str(random.randint(50, 500) * 1000) + " that we need to route\n"
            "through the " + random.choice(BANKS) + " account ending in " + str(random.randint(1000,9999)) + ".\n\n"
            "Please make sure the wire transfer goes out before the external auditors arrive on\n"
            + (dt + timedelta(days=random.randint(3,14))).strftime('%B %d') + ". Use reference code\n"
            + ref + " and mark it as consulting services per our arrangement.\n\n"
            "I have also attached the updated spreadsheet with the real numbers hidden in a separate\n"
            "tab (password: " + rand_md5()[:12] + "). Do NOT forward this to anyone outside our group.\n\n"
            "Let me know once the transfer is confirmed.\n\n"
            "Best regards,\n" + sender[0] + "\n" + sender[1] + "\nDirect: " + sender[2]
        ),
        lambda: (
            recip[0].split()[0] + ",\n\n"
            "The package has been delivered to the drop location. Our contact in "
            + random.choice(['Dubai', 'Singapore', 'Zurich', 'Panama City', 'Hong Kong', 'Cayman Islands']) + "\n"
            "confirmed receipt at " + fmt_dt(dt) + ". Transaction hash: " + rand_hash()[:16] + "\n\n"
            "Total value: " + str(round(random.uniform(10, 500), 4)) + " BTC (approx. $" + str(random.randint(50000, 2000000)) + ")\n"
            "Wallet: " + random.choice(CRYPTO_WALLETS) + "\n\n"
            "The " + random.choice(MALWARE_NAMES) + " deployment is scheduled for "
            + (dt + timedelta(hours=random.randint(6,72))).strftime('%A at %H:%M UTC') + ".\n"
            "Make sure the C2 server at " + rand_ip() + " is ready to receive callbacks.\n\n"
            "Burn this message after reading.\n\n"
            "-- " + sender[0].split()[0][0] + "." + sender[0].split()[-1][0] + "."
        ),
        lambda: (
            "Team,\n\n"
            "Following up on the incident response call. Here is the current timeline:\n\n"
            + fmt_dt(dt - timedelta(hours=random.randint(12,72))) + " - Initial compromise detected via anomalous DNS queries to " + random.choice(DOMAINS) + "\n"
            + fmt_dt(dt - timedelta(hours=random.randint(6,11))) + " - Lateral movement observed: " + rand_ip() + " to " + rand_ip() + " via SMB\n"
            + fmt_dt(dt - timedelta(hours=random.randint(2,5))) + " - Data exfiltration confirmed: ~" + str(random.randint(5, 500)) + " GB transferred to " + rand_ip() + "\n"
            + fmt_dt(dt) + " - Containment initiated: affected systems isolated\n\n"
            "Affected systems:\n"
            "  - WORKSTATION-" + str(random.randint(100,999)) + " (" + rand_ip() + ") - " + random.choice(SUSPECTS)[0] + " machine\n"
            "  - SRV-DB-" + str(random.randint(10,99)) + " (" + rand_ip() + ") - Primary database server\n"
            "  - SRV-FILE-" + str(random.randint(10,99)) + " (" + rand_ip() + ") - File server containing PII\n\n"
            "The threat actor used " + random.choice(MALWARE_NAMES) + " for initial access and " + random.choice(MALWARE_NAMES) + "\n"
            "for persistence. IOCs have been shared with the SOC team.\n\n"
            "Forensic images are being acquired. Chain of custody forms attached.\n\n"
            + sender[0] + "\nSenior Incident Responder\n" + sender[1]
        ),
        lambda: (
            recip[0].split()[0] + ",\n\n"
            "I need you to access the following accounts and move everything to the new\n"
            "holding company before the end of business " + (dt + timedelta(days=random.randint(1,5))).strftime('%A') + ":\n\n"
            "1. " + random.choice(BANKS) + " - Acct #" + str(random.randint(10000000, 99999999)) + " - Balance: $" + str(random.randint(100, 9999) * 1000) + "\n"
            "2. " + random.choice(BANKS) + " - Acct #" + str(random.randint(10000000, 99999999)) + " - Balance: EUR " + str(random.randint(100, 5000) * 1000) + "\n"
            "3. " + random.choice(BANKS) + " - Acct #" + str(random.randint(10000000, 99999999)) + " - Balance: GBP " + str(random.randint(50, 3000) * 1000) + "\n\n"
            "Route the transfers through " + random.choice(['Shell Holdings Panama', 'Blue Horizon Trust Ltd', 'Pacific Ventures BVI', 'Nordic Capital Partners AG']) + "\n"
            "to maintain separation. Use the usual layering pattern:\n\n"
            "  Wire -> Correspondent Bank -> Intermediary -> Final Destination\n\n"
            "The compliance officer at " + random.choice(BANKS) + " has been handled - reference\n"
            "code GAMMA-" + str(random.randint(100,999)) + " for expedited processing.\n\n"
            "Delete this email and clear your sent items.\n\n"
            + sender[0]
        ),
    ]

    body = random.choice(body_templates)()
    case_id = random.choice(CASE_IDS)

    return (
        "=" * 80 + "\n"
        "ELECTRONIC MAIL EVIDENCE - " + case_id + "\n"
        "Extracted from: " + random.choice(FILE_PATHS_WIN) + "\n"
        "Evidence Hash (SHA-256): " + rand_hash() + "\n"
        "=" * 80 + "\n"
        "From: " + sender[0] + " <" + sender[1] + ">\n"
        "To: " + recip[0] + " <" + recip[1] + ">\n"
        "Date: " + fmt_dt(dt) + "\n"
        "Subject: " + subj + "\n"
        "Message-ID: <" + str(uuid.uuid4()) + "@" + random.choice(DOMAINS) + ">\n"
        "X-Mailer: Microsoft Outlook 16.0\n"
        "X-Originating-IP: [" + rand_ip() + "]\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n\n"
        + body + "\n\n"
        "=" * 80 + "\n\n"
    )


def gen_chat_log():
    platform = random.choice(["Telegram", "Signal", "WhatsApp", "Wickr", "Discord"])
    participants = random.sample(SUSPECTS, k=random.randint(2, 4))
    dt = rand_dt()
    case_id, case_name = rand_case()
    conversations = []

    msg_templates = [
        "Have you checked the latest transfer? ${amt} went through at {time}.",
        "The server at {ip} is compromised. We need to move fast.",
        "Password for the encrypted archive: {password}",
        "Meeting at the usual place. {day} at {hour}:00.",
        "The auditors are asking questions about the {bank} account. Stay calm.",
        "I have uploaded the files to {ip}. Directory: /tmp/.cache/{hash8}",
        "New wallet address: {wallet}",
        "The {malware} payload is ready. Deploying in {hours} hours.",
        "Delete everything on {path}. NOW.",
        "Our contact at {bank} says the wire cleared. Confirmation: {ref}",
        "Can you verify the hash? {hash_type}: {hash32}",
        "The shipment arrives {day}. Container #{ref}.",
        "I have modified the financial reports. The real numbers are in the hidden tab.",
        "Do not use this channel anymore. Switch to {alt_platform}.",
        "The backdoor on {ip} is still active. Last callback: {time}.",
        "We need to create {count} shell companies before the end of the quarter.",
        "The cryptocurrency tumbler processed {btc_amt} BTC successfully.",
        "FBI is investigating {company}. We need to distance ourselves.",
        "I have set up a dead drop at coordinates {lat}, {lon}.",
        "The insider at {company} wants ${amt} for the data.",
        "Run the exploit against {ip}. CVE-{cve} should give us root.",
        "The phishing campaign targeting {company} employees went live at {time}.",
        "I need access to the {bank} safety deposit box. Key code: {ref}.",
        "The evidence has been planted. {suspect} will take the fall.",
        "Wipe the burner phones after this conversation.",
    ]

    for i in range(random.randint(12, 30)):
        speaker = random.choice(participants)
        msg_dt = dt + timedelta(minutes=random.randint(0, i * 15))
        template = random.choice(msg_templates)
        msg = template.format(
            amt=str(random.randint(1000, 9999999)),
            time=fmt_dt(msg_dt),
            ip=rand_ip(),
            password=rand_md5()[:16],
            day=(msg_dt + timedelta(days=random.randint(1,7))).strftime("%A"),
            hour=random.randint(6, 23),
            bank=random.choice(BANKS),
            hash8=rand_hash()[:8],
            hash32=rand_hash()[:32],
            wallet=random.choice(CRYPTO_WALLETS),
            malware=random.choice(MALWARE_NAMES),
            hours=random.randint(2, 48),
            path=random.choice(FILE_PATHS_WIN + FILE_PATHS_LINUX),
            ref=str(random.randint(100000, 999999)),
            hash_type=random.choice(HASH_ALGOS),
            alt_platform=random.choice(["Telegram", "Signal", "Wickr"]),
            count=random.randint(3, 15),
            company=random.choice(DOMAINS),
            lat=str(round(random.uniform(25, 55), 6)),
            lon=str(round(random.uniform(-120, 40), 6)),
            cve="2025-" + str(random.randint(10000,99999)),
            suspect=random.choice(SUSPECTS)[0],
            btc_amt=str(round(random.uniform(0.5, 100), 4)),
        )
        conversations.append("[" + fmt_dt(msg_dt) + "] " + speaker[0] + ": " + msg)

    header = (
        "-" * 80 + "\n"
        "CHAT LOG EXTRACTION - " + case_id + "\n"
        "Case: " + case_name + "\n"
        "Platform: " + platform + " (Encrypted Messaging)\n"
        "Extraction Tool: Cellebrite UFED Premium v7." + str(random.randint(40,65)) + "\n"
        "Device: " + random.choice(['iPhone 15 Pro', 'Samsung Galaxy S24', 'Google Pixel 8', 'OnePlus 12'])
        + " - IMEI: " + str(random.randint(100000000000000, 999999999999999)) + "\n"
        "Participants: " + ", ".join(p[0] + " (" + p[2] + ")" for p in participants) + "\n"
        "Extraction Date: " + fmt_dt(rand_dt()) + "\n"
        "Evidence Hash (SHA-256): " + rand_hash() + "\n"
        "-" * 80 + "\n"
    )
    return header + "\n".join(conversations) + "\n\n"


def gen_financial_records():
    dt = rand_dt()
    case_id, case_name = rand_case()
    num_txns = random.randint(15, 40)
    suspect = rand_suspect()
    analyst = rand_suspect()

    lines = []
    lines.append("=" * 80 + "\n")
    lines.append("FINANCIAL TRANSACTION ANALYSIS - " + case_id + "\n")
    lines.append("Case: " + case_name + "\n")
    lines.append("Source: Subpoenaed bank records - " + random.choice(BANKS) + "\n")
    lines.append("Account Holder: " + suspect[0] + "\n")
    lines.append("Account Number: " + random.choice(['IBAN: ', 'Acct: '])
                 + random.choice(['GB','CH','KY','PA','LU'])
                 + str(random.randint(10, 99)) + " "
                 + str(random.randint(1000,9999)) + " "
                 + str(random.randint(1000,9999)) + " "
                 + str(random.randint(1000,9999)) + " "
                 + str(random.randint(1000,9999)) + "\n")
    lines.append("Analysis Period: " + dt.strftime('%Y-%m-%d') + " to "
                 + (dt + timedelta(days=random.randint(30,180))).strftime('%Y-%m-%d') + "\n")
    lines.append("Analyst: Forensic Accountant " + analyst[0] + "\n")
    lines.append("=" * 80 + "\n\n")

    txn_types = ["Wire Transfer", "ACH Transfer", "Check Deposit", "Cash Deposit",
                 "International Wire", "Crypto Purchase", "Standing Order",
                 "SWIFT Transfer", "Internal Transfer", "Cash Withdrawal"]

    flags = ["", "", "", "STRUCTURING", "ROUND AMOUNT", "SAR FILED",
             "HIGH RISK JURISDICTION", "", "UNUSUAL PATTERN", "", "",
             "SANCTIONS MATCH", "", "RAPID MOVEMENT"]

    counterparties = [
        "Shell Holdings Panama SA", "Blue Horizon Trust Ltd", "Pacific Ventures BVI",
        "Nordic Capital Partners AG", "Golden Gate Consulting LLC", "Apex Trading FZE",
        "Meridian Financial Services", "Atlas Offshore Holdings", "Zenith Capital Management",
        "Shadow Creek Investments", "Ironclad Security Solutions", "Quantum Dynamics Corp",
    ] + [s[0] for s in SUSPECTS]

    total = 0
    for i in range(num_txns):
        txn_dt = dt + timedelta(days=random.randint(0, 180))
        txn_type = random.choice(txn_types)
        currency = random.choice(CURRENCIES[:4])
        if "Cash" in txn_type:
            amount = random.randint(1, 99) * 100
        else:
            amount = random.randint(500, 9999999)
        flag = random.choice(flags)
        total += amount
        flag_str = " [FLAG: " + flag + "]" if flag else ""
        lines.append(
            fmt_dt(txn_dt) + " | " + txn_type + " | "
            + str(amount) + ".00 " + currency + " | "
            + random.choice(counterparties) + " | REF-"
            + str(random.randint(100000,999999)) + flag_str + "\n"
        )

    lines.append("\n" + "-" * 80 + "\n")
    lines.append("TOTAL TRANSACTION VOLUME: " + str(total) + ".00\n")
    lines.append("SUSPICIOUS TRANSACTIONS FLAGGED: " + str(random.randint(3, max(4, num_txns//3))) + "\n")
    lines.append("SAR FILINGS RECOMMENDED: " + str(random.randint(1, 5)) + "\n\n")

    return "".join(lines)


def gen_network_logs():
    dt = rand_dt()
    case_id = random.choice(CASE_IDS)
    num_entries = random.randint(30, 60)

    header = (
        "#" * 80 + "\n"
        "NETWORK / FIREWALL / IDS LOG EXTRACT - " + case_id + "\n"
        "Source: " + random.choice(['Palo Alto PA-5250', 'Fortinet FortiGate 600E', 'Cisco ASA 5585-X', 'Snort IDS v3.1']) + "\n"
        "Time Range: " + fmt_dt(dt) + " - " + fmt_dt(dt + timedelta(hours=random.randint(2, 48))) + "\n"
        "Extracted By: " + rand_suspect()[0] + " - Digital Forensics Unit\n"
        "#" * 80 + "\n\n"
    )
    entries = []

    for i in range(num_entries):
        log_dt = dt + timedelta(seconds=random.randint(0, i * 120))
        log_type = random.randint(0, 9)
        ts = fmt_dt(log_dt)

        if log_type == 0:
            entry = ts + " FIREWALL DENY  src=" + rand_ip() + ":" + str(random.randint(1024,65535)) + " dst=" + rand_ip() + ":" + str(random.choice([22,80,443,445,3389,8080,8443,4444,5555])) + " proto=TCP rule=BLOCK_SUSPICIOUS"
        elif log_type == 1:
            entry = ts + " IDS ALERT      [1:" + str(random.randint(1000000,9999999)) + ":" + str(random.randint(1,20)) + "] ET MALWARE " + random.choice(MALWARE_NAMES) + " C2 Beacon Detected src=" + rand_ip() + " dst=" + rand_ip()
        elif log_type == 2:
            entry = ts + " DNS QUERY      client=" + rand_ip() + " query=" + random.choice(['evil','c2','update','api','cdn','ns1']) + "." + random.choice(DOMAINS) + " type=A response=" + rand_ip()
        elif log_type == 3:
            entry = ts + " FIREWALL ALLOW src=" + rand_ip() + ":" + str(random.randint(1024,65535)) + " dst=" + rand_ip() + ":" + str(random.choice([443,8443])) + " proto=TCP bytes_sent=" + str(random.randint(100,999999)) + " bytes_recv=" + str(random.randint(100,9999999)) + " duration=" + str(random.randint(1,3600)) + "s"
        elif log_type == 4:
            entry = ts + " AUTH FAILURE   src=" + rand_ip() + " user=" + random.choice(SUSPECTS)[1].split('@')[0] + " service=SSH attempt=" + str(random.randint(1,50))
        elif log_type == 5:
            entry = ts + " DATA EXFIL     src=" + rand_ip() + " dst=" + rand_ip() + " proto=HTTPS volume=" + str(random.randint(1,500)) + "GB duration=" + str(random.randint(60,7200)) + "s ANOMALOUS TRANSFER"
        elif log_type == 6:
            entry = ts + " VPN CONNECT    user=" + random.choice(SUSPECTS)[1].split('@')[0] + " src_ip=" + rand_ip() + " vpn_ip=10.8.0." + str(random.randint(2,254)) + " geo=" + random.choice(['RU','CN','IR','KP','US','GB','DE','BR'])
        elif log_type == 7:
            entry = ts + " PROXY BLOCK    client=" + rand_ip() + " url=https://" + random.choice(DOMAINS) + "/" + random.choice(['upload','download','exfil','data','dump']) + "/" + rand_md5()[:8] + " category=MALICIOUS"
        elif log_type == 8:
            entry = ts + " SCAN DETECT    src=" + rand_ip() + " type=" + random.choice(['SYN_SCAN','PORT_SWEEP','OS_FINGERPRINT','VULN_SCAN']) + " targets=" + str(random.randint(5,255)) + " ports=" + str(random.randint(100,65535))
        else:
            entry = ts + " LATERAL MOVE   src=" + rand_ip() + " dst=" + rand_ip() + " method=" + random.choice(['PSExec','WMI','RDP','SMB','WinRM']) + " user=" + random.choice(SUSPECTS)[1].split('@')[0]
        entries.append(entry)

    return header + "\n".join(entries) + "\n\n"


def gen_file_metadata():
    case_id = random.choice(CASE_IDS)
    num_files = random.randint(15, 35)

    header = (
        "=" * 80 + "\n"
        "FILE SYSTEM METADATA AND HASH MANIFEST - " + case_id + "\n"
        "Image Source: " + random.choice(['Forensic disk image (E01)', 'Live acquisition (raw/dd)', 'Logical extraction', 'Cloud storage mirror']) + "\n"
        "Tool: " + random.choice(['Autopsy 4.21', 'FTK Imager 4.7', 'X-Ways Forensics 20.9', 'EnCase 22.4']) + "\n"
        "Examiner: " + rand_suspect()[0] + "\n"
        "Acquisition Date: " + fmt_dt(rand_dt()) + "\n"
        "=" * 80 + "\n\n"
    )
    entries = []

    notes_list = [
        'Flagged by keyword search - contains financial data',
        'Suspicious: created outside business hours',
        'Matches known malware hash in VirusTotal',
        'Contains PII - SSN/credit card numbers detected',
        'Steganography suspected - file size anomalous for type',
        'Metadata stripped - anti-forensic technique',
        'Recently accessed after employee termination',
        'Located in hidden directory - possible concealment',
        'File extension mismatch - .jpg header but .exe content',
        'Timestamp anomaly - MAC times inconsistent',
    ]

    all_paths = FILE_PATHS_WIN + FILE_PATHS_LINUX

    for i in range(num_files):
        path = random.choice(all_paths)
        dt_created  = rand_dt()
        dt_modified = dt_created + timedelta(hours=random.randint(0, 720))
        dt_accessed = dt_modified + timedelta(hours=random.randint(0, 168))
        size = random.randint(1024, 500 * 1024 * 1024)

        if size > 1024*1024:
            size_str = str(round(size / (1024*1024), 1)) + " MB"
        else:
            size_str = str(round(size / 1024, 1)) + " KB"

        deleted = random.random() < 0.2
        encrypted = random.random() < 0.15
        status = "DELETED (recovered from unallocated space)" if deleted else "Active"
        if encrypted:
            status += " | ENCRYPTED (AES-256)"

        entries.append(
            "  File #" + str(i+1) + ":\n"
            "    Path:       " + path + "\n"
            "    Size:       " + size_str + " (" + str(size) + " bytes)\n"
            "    Created:    " + fmt_dt(dt_created) + "\n"
            "    Modified:   " + fmt_dt(dt_modified) + "\n"
            "    Accessed:   " + fmt_dt(dt_accessed) + "\n"
            "    MD5:        " + rand_md5() + "\n"
            "    SHA-256:    " + rand_hash() + "\n"
            "    Owner:      " + random.choice(SUSPECTS)[1].split('@')[0] + "\n"
            "    Status:     " + status + "\n"
            "    Notes:      " + random.choice(notes_list) + "\n\n"
        )

    return header + "\n".join(entries) + "\n"


def gen_browser_history():
    dt = rand_dt()
    suspect = rand_suspect()
    case_id = random.choice(CASE_IDS)
    num_entries = random.randint(20, 40)

    header = (
        "=" * 80 + "\n"
        "BROWSER HISTORY AND SEARCH QUERY EXTRACTION - " + case_id + "\n"
        "User Profile: " + suspect[0] + " (" + suspect[1] + ")\n"
        "Browser: " + random.choice(['Google Chrome 125.0', 'Mozilla Firefox 126.0', 'Microsoft Edge 125.0', 'Brave 1.66']) + "\n"
        "Machine: WORKSTATION-" + str(random.randint(100,999)) + " (" + rand_ip() + ")\n"
        "Extraction Period: " + fmt_dt(dt - timedelta(days=30)) + " - " + fmt_dt(dt) + "\n"
        "=" * 80 + "\n\n"
    )
    entries = []

    urls_and_titles = [
        ("https://www.offshore-banking-guide.com/anonymous-accounts", "How to Open Anonymous Offshore Bank Accounts"),
        ("https://bitcoin-mixer.onion/tumble", "Bitcoin Tumbler - Anonymous Crypto Mixing"),
        ("https://mail.vortexcorp.com/inbox", "Webmail - vortexcorp.com"),
        ("https://www.how-to-encrypt-files.com/veracrypt-guide", "VeraCrypt Full Disk Encryption Tutorial"),
        ("https://duckduckgo.com/?q=how+to+delete+browser+history+permanently", "how to delete browser history permanently"),
        ("https://www.investopedia.com/terms/m/moneylaundering.asp", "Money Laundering Definition - Investopedia"),
        ("https://darknode.io/admin/panel", "Admin Panel - Server Management"),
        ("https://github.com/threat-actor/persistence-toolkit", "persistence-toolkit - GitHub"),
        ("https://www.irs.gov/compliance/criminal-investigation", "IRS Criminal Investigation"),
        ("https://www.sec.gov/whistleblower", "SEC Whistleblower Program"),
        ("https://stackoverflow.com/questions/how-to-exfiltrate-data-over-dns", "How to tunnel data over DNS - Stack Overflow"),
        ("https://www.cayman-company-formation.com/pricing", "Cayman Islands Company Formation - Pricing"),
        ("https://blockchain.com/btc/address/bc1q_example", "Bitcoin Address - Blockchain Explorer"),
        ("https://www.anti-forensics.com/file-wiping-tools", "File Wiping Tools - Anti-Forensics"),
        ("https://www.darkwebmarkets.org/listings", "Dark Web Markets - Current Listings"),
        ("https://drive.google.com/file/d/shared_doc_id/view", "Shared Document - Google Drive"),
        ("https://haveibeenpwned.com/", "Have I Been Pwned - Check Email Breach"),
        ("https://whatismyipaddress.com/", "What Is My IP Address"),
        ("https://www.vpn-comparison.net/no-logs-vpn", "Best No-Logs VPN Services 2025"),
        ("https://www.wikileaks.org/", "WikiLeaks"),
    ]

    for i in range(num_entries):
        visit_dt = dt - timedelta(minutes=random.randint(0, 43200))
        url, title = random.choice(urls_and_titles)
        duration = random.randint(5, 1800)
        entries.append(
            "  [" + fmt_dt(visit_dt) + "]  Duration: " + str(duration) + "s  |  " + title + "\n"
            "    URL: " + url + "\n"
            "    Referrer: " + random.choice(['Direct', 'Google Search', 'DuckDuckGo', 'Bookmark']) + "\n"
        )

    search_queries = [
        "how to hide money from IRS",
        "best cryptocurrency for anonymous transactions",
        "delete files permanently windows forensics",
        "offshore bank account minimum deposit",
        "how to set up shell company panama",
        "anti-forensic tools 2025",
        "encrypt hard drive before investigation",
        "statute of limitations wire fraud",
        "VPN that does not keep logs",
        "how to create fake invoices",
        "evidence tampering penalties US",
        "best dark web browser",
        "how to spot a wiretap",
        "cryptocurrency tumbling service",
        "employee data theft detection",
        "digital forensics what can they find",
        "how to permanently delete emails",
        "burner phone purchase anonymous",
        "extradition treaty countries list",
        "ransomware payment bitcoin",
    ]

    entries.append("\n  " + "-" * 60 + "\n  SEARCH QUERIES (extracted from browser SQLite database)\n  " + "-" * 60 + "\n")
    for q in random.sample(search_queries, k=min(random.randint(8, 15), len(search_queries))):
        q_dt = dt - timedelta(minutes=random.randint(0, 43200))
        entries.append("  [" + fmt_dt(q_dt) + "]  SEARCH: \"" + q + "\"\n")

    return header + "\n".join(entries) + "\n\n"


def gen_incident_report():
    dt = rand_dt()
    case_id, case_name = rand_case()
    lead = rand_suspect()

    report_type = random.choice(["INITIAL INCIDENT REPORT", "FORENSIC EXAMINATION REPORT"])

    if report_type == "INITIAL INCIDENT REPORT":
        body = (
            "INCIDENT CLASSIFICATION: " + random.choice(['Data Breach', 'Ransomware Attack', 'Insider Threat', 'Corporate Fraud', 'Network Intrusion', 'IP Theft']) + "\n"
            "SEVERITY LEVEL: " + random.choice(['CRITICAL', 'HIGH', 'MEDIUM']) + "\n"
            "DATE OF DISCOVERY: " + fmt_dt(dt) + "\n"
            "DATE OF INITIAL COMPROMISE (estimated): " + fmt_dt(dt - timedelta(days=random.randint(7, 180))) + "\n"
            "REPORTING OFFICER: " + lead[0] + "\n\n"
            "EXECUTIVE SUMMARY:\n"
            "On " + dt.strftime('%B %d, %Y') + ", the Security Operations Center (SOC) detected anomalous\n"
            "activity originating from internal network segment 10.0.14.0/24. Investigation revealed\n"
            "that threat actor(s) had gained unauthorized access to critical systems containing\n"
            + random.choice(['personally identifiable information (PII)', 'protected health information (PHI)', 'financial records', 'trade secrets', 'classified documents']) + "\n"
            "affecting approximately " + str(random.randint(1000, 500000)) + " " + random.choice(['individuals', 'records', 'accounts']) + ".\n\n"
            "ATTACK VECTOR:\n"
            "The initial compromise was achieved through " + random.choice([
                'a spear-phishing email targeting ' + rand_suspect()[0] + ' containing a malicious attachment',
                'exploitation of CVE-2025-' + str(random.randint(10000,99999)) + ' in the public-facing web application',
                'compromised VPN credentials purchased from a dark web marketplace',
                'an insider threat - ' + rand_suspect()[0] + ' intentionally introduced malware',
                'supply chain compromise via a third-party software update',
                'brute-force attack against the RDP service exposed on port 3389',
            ]) + "\n\n"
            "SYSTEMS AFFECTED:\n"
            "  1. " + rand_ip() + " - " + random.choice(['Domain Controller', 'Database Server', 'File Server', 'Email Server', 'Web Application Server']) + "\n"
            "  2. " + rand_ip() + " - " + random.choice(['HR System', 'Financial Database', 'Customer Portal', 'Development Server']) + "\n"
            "  3. " + rand_ip() + " - " + random.choice(SUSPECTS)[0] + " workstation\n"
            "  4. " + rand_ip() + " - " + random.choice(['Backup Server', 'Print Server', 'CCTV System', 'Badge Access Controller']) + "\n\n"
            "INDICATORS OF COMPROMISE (IOCs):\n"
            "  - Malicious IP: " + rand_ip() + "\n"
            "  - C2 Domain: c2-" + rand_md5()[:8] + "." + random.choice(DOMAINS) + "\n"
            "  - Malware Hash (SHA-256): " + rand_hash() + "\n"
            "  - Malware Family: " + random.choice(MALWARE_NAMES) + "\n"
            "  - Persistence: " + random.choice(['Scheduled Task', 'Registry Run Key', 'WMI Event Subscription', 'DLL Hijacking', 'Bootkit']) + "\n"
            "  - Lateral Movement: " + random.choice(['Pass-the-Hash', 'Kerberoasting', 'Golden Ticket', 'PSExec', 'WMI']) + "\n\n"
            "DATA IMPACT:\n"
            "  - Records exposed: " + str(random.randint(1000, 500000)) + "\n"
            "  - Data volume exfiltrated: ~" + str(random.randint(1, 500)) + " GB\n"
            "  - Data types: SSN, Credit Cards, Bank Accounts, Employee Records\n\n"
            "IMMEDIATE ACTIONS TAKEN:\n"
            "  1. Isolated affected network segments\n"
            "  2. Initiated forensic imaging of " + str(random.randint(3, 20)) + " systems\n"
            "  3. Engaged " + random.choice(['CrowdStrike', 'Mandiant', 'Secureworks', 'Kroll']) + " for incident response\n"
            "  4. Notified " + random.choice(['FBI Cyber Division', 'CISA', 'IC3', 'local law enforcement']) + "\n"
            "  5. Activated crisis communication plan\n"
        )
    else:
        body = (
            "EXAMINER: " + lead[0] + " - Certified Forensic Computer Examiner (CFCE #" + str(random.randint(10000,99999)) + ")\n"
            "EXAMINATION DATE: " + fmt_dt(dt) + "\n"
            "LAB: Digital Forensics Laboratory - Room " + str(random.randint(100,999)) + "\n\n"
            "EVIDENCE EXAMINED:\n"
            "  Item #1: " + random.choice(['Western Digital 2TB HDD', 'Samsung 1TB NVMe SSD', 'Seagate 4TB External', 'Kingston 256GB USB']) + "\n"
            "           Serial: " + rand_md5()[:12].upper() + "\n"
            "           Acquisition Hash (SHA-256): " + rand_hash() + "\n\n"
            "  Item #2: " + random.choice(['iPhone 15 Pro Max', 'Samsung Galaxy S24 Ultra', 'Google Pixel 8 Pro']) + "\n"
            "           IMEI: " + str(random.randint(100000000000000, 999999999999999)) + "\n"
            "           Extraction Type: " + random.choice(['Full File System', 'Physical', 'Logical', 'Advanced Logical']) + "\n\n"
            "EXAMINATION METHODOLOGY:\n"
            "  1. Evidence received and documented per department SOP\n"
            "  2. Write-blocked forensic acquisition performed using " + random.choice(['FTK Imager', 'dd/dcfldd', 'Magnet ACQUIRE', 'Cellebrite UFED']) + "\n"
            "  3. Hash verification - acquisition hash matches original: VERIFIED\n"
            "  4. Analysis performed in isolated forensic workstation (air-gapped)\n"
            "  5. Keyword searches conducted for " + str(random.randint(50, 500)) + " terms\n"
            "  6. Timeline analysis generated using " + random.choice(['log2timeline/Plaso', 'Axiom Timeline', 'X-Ways Timeline']) + "\n\n"
            "KEY FINDINGS:\n"
            "  Finding 1: Evidence of data exfiltration\n"
            "    - " + rand_suspect()[0] + " accessed " + str(random.randint(50, 5000)) + " files containing sensitive data\n"
            "      between " + fmt_dt(dt - timedelta(days=random.randint(7,60))) + " and " + fmt_dt(dt) + "\n"
            "    - Files were compressed using 7-Zip and encrypted with AES-256\n"
            "    - Encrypted archives were uploaded to " + random.choice(['personal Google Drive', 'anonymous Mega.nz account', 'self-hosted cloud server at ' + rand_ip(), 'USB device (not recovered)']) + "\n\n"
            "  Finding 2: Anti-forensic activity detected\n"
            "    - " + random.choice(['CCleaner', 'BleachBit', 'Eraser', 'SDelete']) + " was installed on " + fmt_dt(dt - timedelta(days=random.randint(1,14))) + "\n"
            "    - " + str(random.randint(500, 50000)) + " files in the Recycle Bin were securely wiped\n"
            "    - Browser history cleared " + str(random.randint(3, 20)) + " times in the examination period\n"
            "    - " + random.choice(['Timestomping detected - file dates manipulated', 'USN Journal partially cleared', 'Event logs selectively deleted', 'Prefetch files removed']) + "\n\n"
            "  Finding 3: Communication with known threat actors\n"
            "    - " + random.choice(['Signal', 'Telegram', 'Wickr']) + " messages recovered from device backup\n"
            "    - " + str(random.randint(50, 500)) + " messages exchanged with " + rand_suspect()[0] + " (" + rand_suspect()[2] + ")\n"
            "    - Discussion topics include: payment arrangements, data delivery, cover stories\n\n"
            "  Finding 4: Financial irregularities\n"
            "    - Spreadsheets found containing " + random.choice(['dual bookkeeping entries', 'fabricated invoices totaling $' + str(random.randint(100,9999)*1000), 'hidden formulas calculating embezzlement amounts', 'offshore account routing instructions']) + "\n"
            "    - Browser bookmarks include " + random.choice(BANKS) + " online banking portal\n"
            "    - Cryptocurrency wallet software (" + random.choice(['Electrum', 'Exodus', 'Wasabi']) + ") installed with transaction history showing " + str(round(random.uniform(1, 100), 4)) + " BTC\n\n"
            "CHAIN OF CUSTODY:\n"
            "  " + fmt_dt(dt - timedelta(days=random.randint(5,30))) + " - Evidence seized by " + rand_suspect()[0] + " (Badge #" + str(random.randint(1000,9999)) + ")\n"
            "  " + fmt_dt(dt - timedelta(days=random.randint(3,4))) + " - Transported to forensic lab - sealed evidence bag #" + str(random.randint(100000,999999)) + "\n"
            "  " + fmt_dt(dt - timedelta(days=random.randint(1,2))) + " - Received by examiner " + lead[0] + " - integrity seal verified\n"
            "  " + fmt_dt(dt) + " - Examination commenced\n"
        )

    return (
        "=" * 80 + "\n"
        + report_type + " - " + case_id + "\n"
        "Case: " + case_name + "\n"
        "Classification: " + random.choice(['LAW ENFORCEMENT SENSITIVE', 'CONFIDENTIAL', 'FOR OFFICIAL USE ONLY']) + "\n"
        "=" * 80 + "\n\n"
        + body + "\n"
        "=" * 80 + "\n\n"
    )


def gen_registry_artifacts():
    dt = rand_dt()
    suspect = rand_suspect()
    case_id = random.choice(CASE_IDS)

    parts = []
    parts.append("=" * 80 + "\n")
    parts.append("WINDOWS REGISTRY ARTIFACT ANALYSIS - " + case_id + "\n")
    parts.append("Source: NTUSER.DAT - " + suspect[0] + " (" + suspect[1] + ")\n")
    parts.append("Machine: WORKSTATION-" + str(random.randint(100,999)) + "\n")
    parts.append("Extracted: " + fmt_dt(dt) + "\n")
    parts.append("Tool: " + random.choice(['Registry Explorer v2.0', 'RegRipper 3.0', 'RECmd v2.0']) + "\n")
    parts.append("=" * 80 + "\n\n")

    parts.append("--- RECENT DOCUMENTS (RecentDocs MRU) ---\n")
    for i in range(random.randint(5, 15)):
        parts.append("  [" + str(i+1) + "] " + random.choice(FILE_PATHS_WIN) + "  -  Last opened: " + fmt_dt(rand_dt()) + "\n")

    parts.append("\n--- USB DEVICE HISTORY (USBSTOR) ---\n")
    usb_devices = [
        ("Kingston DataTraveler 64GB", "USB_VID_0951_PID_1666"),
        ("SanDisk Ultra 128GB", "USB_VID_0781_PID_5581"),
        ("Seagate Expansion 2TB", "USB_VID_0BC2_PID_2322"),
        ("Samsung T7 1TB SSD", "USB_VID_04E8_PID_4001"),
        ("Unknown Device", "USB_VID_DEAD_PID_BEEF"),
    ]
    for dev_name, dev_id in random.sample(usb_devices, k=random.randint(2, 5)):
        parts.append(
            "  Device: " + dev_name + "\n"
            "    ID: " + dev_id + "_" + rand_md5()[:12].upper() + "\n"
            "    Serial: " + rand_md5()[:16].upper() + "\n"
            "    First Connected: " + fmt_dt(rand_dt()) + "\n"
            "    Last Connected:  " + fmt_dt(rand_dt()) + "\n"
            "    Volume Name: " + random.choice(['BACKUP', 'DATA', 'USB_DRIVE', 'CONFIDENTIAL', 'NO_NAME', 'EXFIL']) + "\n"
            "    Drive Letter: " + random.choice(['E:', 'F:', 'G:', 'H:']) + "\n"
            "    NOTE: " + random.choice(['Connected after hours', 'Large data transfer detected', 'Device not company-issued', 'Used after termination notice']) + "\n\n"
        )

    parts.append("\n--- AUTORUN / PERSISTENCE ENTRIES ---\n")
    run_entries = [
        ("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "UpdateService", "C:\\Users\\Public\\svchost.exe -hidden"),
        ("HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "SystemHealth", "C:\\Windows\\Temp\\health_check.exe"),
        ("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce", "CleanUp", "cmd.exe /c del /q C:\\Users\\%USERNAME%\\Documents\\*.log"),
        ("HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "SecurityUpdate", "powershell.exe -enc " + rand_md5()[:40]),
    ]
    for key, name, value in run_entries:
        parts.append("  Key:   " + key + "\n  Name:  " + name + "\n  Value: " + value + "\n  SUSPICIOUS - Not a legitimate application\n\n")

    parts.append("--- SHELLBAGS (Directory Access History) ---\n")
    shell_dirs = [
        "C:\\Users\\" + suspect[0].split()[0].lower() + "\\Documents\\Confidential",
        "\\\\FileServer\\Finance\\Restricted",
        "D:\\Encrypted",
        "C:\\Users\\" + suspect[0].split()[0].lower() + "\\AppData\\Local\\Temp\\exfil",
        "\\\\10.0.14.55\\C$\\Users\\admin\\Desktop",
        "E:\\USB_BACKUP\\client_data",
    ]
    for d in shell_dirs:
        parts.append("  [" + fmt_dt(rand_dt()) + "] Accessed: " + d + "\n")

    return "".join(parts) + "\n\n"


# ── Main Generator ─────────────────────────────────────────────────────────

GENERATORS = [
    (gen_email, 3),
    (gen_chat_log, 2),
    (gen_financial_records, 2),
    (gen_network_logs, 2),
    (gen_file_metadata, 1),
    (gen_browser_history, 1),
    (gen_incident_report, 2),
    (gen_registry_artifacts, 1),
]

def main():
    print("Generating " + str(TARGET_MB) + " MB test evidence file...")
    print("   Output: " + OUT_PATH)

    weighted = []
    for gen_func, weight in GENERATORS:
        weighted.extend([gen_func] * weight)

    written = 0
    block_count = 0
    start = time.time()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        header = (
            "=" * 80 + "\n"
            "INTELLIGENT DIGITAL FORENSIC AI ASSISTANT - MASTER EVIDENCE COMPILATION\n"
            "Classification: LAW ENFORCEMENT SENSITIVE\n"
            "Generated: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC') + "\n"
            "Cases: " + ", ".join(CASE_IDS) + "\n"
            "Total Suspects: " + str(len(SUSPECTS)) + "\n"
            "WARNING: This file contains synthetic test data generated for\n"
            "software testing purposes only. No real persons, organizations,\n"
            "or events are depicted.\n"
            "=" * 80 + "\n\n"
            "CASE MANIFEST:\n"
            "-" * 80 + "\n"
        )
        for cid, cname in zip(CASE_IDS, CASE_NAMES):
            header += "  " + cid + ": " + cname + "\n"
        header += "-" * 80 + "\n\nSUSPECT REGISTRY:\n" + "-" * 80 + "\n"
        for s in SUSPECTS:
            header += "  " + s[0] + " | " + s[1] + " | " + s[2] + "\n"
        header += "-" * 80 + "\n\n"

        f.write(header)
        written += len(header.encode("utf-8"))

        while written < TARGET_BYTES:
            gen_func = random.choice(weighted)
            block = gen_func()
            f.write(block)
            blen = len(block.encode("utf-8"))
            written += blen
            block_count += 1

            if block_count % 100 == 0:
                pct = (written / TARGET_BYTES) * 100
                elapsed = time.time() - start
                rate = written / (1024*1024) / elapsed if elapsed > 0 else 0
                print("   " + str(round(pct, 1)) + "% - " + str(round(written/(1024*1024), 1)) + " MB written - " + str(block_count) + " evidence blocks - " + str(round(rate, 1)) + " MB/s")

    elapsed = time.time() - start
    final_mb = written / (1024 * 1024)
    print("\nDone! Generated " + str(round(final_mb, 1)) + " MB in " + str(round(elapsed, 1)) + "s (" + str(block_count) + " evidence blocks)")
    print("   File: " + OUT_PATH)

if __name__ == "__main__":
    main()

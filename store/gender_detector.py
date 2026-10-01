"""
Intelligent Gender Detector for Bangladeshi / Bengali Customer Names
Supports English transliterations, Banglish variations, and Native Bengali scripts.
"""

import re

# Definite Female prefixes/honorifics & titles (Highest weight)
FEMALE_PREFIXES = {
    'mst', 'mst.', 'most', 'most.', 'mrs', 'mrs.', 'miss', 'miss.', 'begum', 'khanam',
    'khatun', 'মোসা', 'মোসাঃ', 'মোসাম্মৎ', 'বেগম', 'খানম', 'খাতুন', 'উম্মে', 'মিসেস', 'মিস',
    'lady', 'sister', 'dr.mrs'
}

# Definite Male prefixes/honorifics & titles (Highest weight)
MALE_PREFIXES = {
    'md', 'md.', 'mohd', 'mohd.', 'mohammad', 'muhammad', 'mr', 'mr.', 'dr', 'dr.',
    'engr', 'engr.', 'al-haj', 'alhaj', 'al-hajj', 'মাওলানা', 'মোঃ', 'মোহাম্মদ', 'মুহাম্মদ',
    'মিঃ', 'মি.', 'ড.', 'ইঞ্জিঃ', 'জনাব', 'hafez', 'qari', 'prof'
}

# Common Bangladeshi Female Given & Suffix Names
FEMALE_NAME_TOKENS = {
    # English / Banglish
    'nusaiba', 'nusaibah', 'israt', 'jahan', 'disha', 'sonata', 'ameena', 'amina', 'megha', 'sabiha',
    'sadia', 'sumaiya', 'sumaya', 'fatema', 'fatima', 'nusrat', 'tania', 'farzana', 'tasnim',
    'tasneem', 'farhana', 'anika', 'sharmin', 'sarmin', 'samia', 'lamia', 'mim', 'meem',
    'puja', 'pooja', 'priya', 'shirley', 'sultana', 'akter', 'aktar', 'khanam', 'khatun',
    'nesa', 'nahar', 'parvin', 'parveen', 'yasmin', 'jesmin', 'shirin', 'shireen', 'nazmin',
    'afroza', 'laboni', 'rani', 'devi', 'kumari', 'maisha', 'jannat', 'jannatul', 'tamanna',
    'rokeya', 'sabrina', 'nishat', 'shamima', 'tabassum', 'sanjida', 'rubi', 'salma', 'halima',
    'kulsum', 'afia', 'rifat', 'shanta', 'mousumi', 'mowsumi', 'reshma', 'mithila', 'munmun',
    'papia', 'shoma', 'ratna', 'tumpa', 'bonna', 'bristi', 'moni', 'akhi', 'afrin',
    'moli', 'poly', 'champa', 'rina', 'bina', 'dalia', 'mita', 'rita', 'gita', 'tanjina',
    'marufa', 'khadija', 'sumi', 'rupa', 'lubna', 'fahmida', 'shahnaz', 'nurun', 'meherun',
    'mahbuba', 'rehana', 'shabnam', 'suraiya', 'rumana', 'shafali', 'zubaida', 'nilufar',
    'shamsun', 'kaniz', 'nadia', 'mitu', 'shila', 'shikha', 'tripti', 'swapna', 'sopna',
    'nargis', 'roshni', 'humaira', 'muntaha', 'fariha', 'raisa', 'alina', 'zaynab', 'zainab',
    'naima', 'nazifa', 'nabila', 'bushra', 'orpa', 'arpita', 'eshita', 'ananya', 'sneha',
    'mou', 'mouri', 'shuchona', 'shurovi', 'nipa', 'nupur', 'koli', 'bithi', 'keya', 'eti',
    
    # Native Bengali
    'নুসাইবা', 'নুসাইবাহ', 'ইসরাত', 'জাহান', 'দিশা', 'সোনাটা', 'আমীনা', 'আমিনা', 'মেঘা', 'সাবিহা',
    'সাদিয়া', 'সুমাইয়া', 'ফাতেমা', 'ফাতিমা', 'নুসরাত', 'তানিয়া', 'ফারজানা', 'তাসনিম',
    'তাসনীম', 'ফারহানা', 'আনিকা', 'শারমীন', 'শারমিন', 'সারমিন', 'সামিয়া', 'লামিয়া', 'মীম', 'মিম',
    'পূজা', 'প্রিয়া', 'সুলতানা', 'আক্তার', 'আকতার', 'খানম', 'খাতুন', 'নেছা', 'নাহার', 'পারভীন',
    'পারভিন', 'ইয়াসমিন', 'জেসমিন', 'শিরিন', 'শিরীন', 'নাজমিন', 'আফরোজা', 'লাবণী', 'লাবনি',
    'রানী', 'দেবী', 'কুমারী', 'মাইশা', 'জান্নাত', 'জান্নাতুল', 'তামান্না', 'রোকেয়া', 'সাবরিনা',
    'নিশাত', 'শামীমা', 'শামিমা', 'তাবাসসুম', 'সানজিদা', 'রুবি', 'সালমা', 'হালিমা', 'কুলসুম',
    'আফিয়া', 'শান্তা', 'মৌসুমী', 'রেশমা', 'মিথিলা', 'মুনমুন', 'পাপিয়া', 'শোভা', 'রত্না',
    'টুম্পা', 'বন্যা', 'বৃষ্টি', 'মণি', 'মনি', 'আঁখি', 'আফরিন', 'পলি', 'চম্পা', 'রীনা', 'রিনা',
    'বীণা', 'ডালিয়া', 'মিতা', 'রীতা', 'গীতা', 'তানজিনা', 'মারুফা', 'খাদিজা', 'সুমি', 'রূপা',
    'লুবনা', 'ফাহমিদা', 'শাহনাজ', 'নুরুন্নাহার', 'মেহেরুন্নেসা', 'মেহের', 'মাহবুবা', 'রেহানা',
    'শবনম', 'সুরাইয়া', 'রুমানা', 'শেফালী', 'জুবাইদা', 'নিলুফার', 'কানিজ', 'নাদিয়া', 'মিতু',
    'শীলা', 'শিখা', 'তৃপ্তি', 'স্বপ্না', 'নার্গিস', 'হুমায়রা', 'মুনতাহা', 'ফারিহা', 'রাইসা',
    'নাঈমা', 'নাজিফা', 'নাবিলা', 'বুশরা', 'অনন্যা', 'স্নেহা', 'মৌ', 'মৌরি', 'সূচনা', 'সুরভী',
    'নিপা', 'নুপুর', 'কলি', 'বীথি', 'কেয়া', 'ইতি'
}

# Common Bangladeshi Male Given Names
MALE_NAME_TOKENS = {
    # English / Banglish
    'shahariar', 'shahriar', 'imtiaz', 'syed', 'hassan', 'hasan', 'ahmed', 'yasir',
    'hossain', 'hussain', 'islam', 'rahman', 'alam', 'mahmud', 'kabir', 'rakib',
    'sakib', 'shakib', 'tanvir', 'tanveer', 'arif', 'ashik', 'nayeem', 'naim', 'shoaib',
    'zahid', 'imran', 'sohel', 'mehedi', 'sujon', 'sabbir', 'monir', 'sayem', 'masud',
    'kamal', 'rubel', 'faisal', 'anamul', 'mushfiq', 'tamim', 'mahmudullah', 'mustafiz',
    'taskin', 'soumya', 'liton', 'bijoy', 'shanto', 'tawhid', 'hridoy', 'shoriful',
    'ebadat', 'khaled', 'nasum', 'mehidy', 'shakil', 'shahid', 'shahin', 'emon', 'mizan',
    'mizanur', 'jahangir', 'anwar', 'alamgir', 'helal', 'delowar', 'delwar', 'momin',
    'motaleb', 'abdul', 'abdullah', 'abdur', 'kawsar', 'kausar', 'sazzad', 'sajid', 'saad',
    'fahim', 'nahid', 'nabil', 'shuvo', 'subroto', 'joy', 'dipu', 'polash', 'mithun',
    'badhon', 'rajib', 'tariq', 'tariqul', 'shafi', 'habib', 'habibur', 'ziar', 'monjur',
    'selim', 'solaiman', 'siddiq', 'ashraf', 'asad', 'asif', 'rayhan', 'raihan', 'alvi',
    'wasim', 'babu', 'khokon', 'sumon', 'jamil', 'jakir', 'zakir', 'maksud', 'bappy',
    'bappi', 'sohan', 'shohag', 'farid', 'harun', 'shorif', 'sharif', 'maruf', 'siam',
    'omor', 'omar', 'osman', 'usman', 'ali', 'gias', 'saiful', 'siraj', 'sirajul',
    'jalal', 'latif', 'mannan', 'shafiq', 'tushar', 'mahbub', 'iqbal', 'parvez', 'shanto',
    'tamzid', 'murshed', 'golam', 'rabbi', 'farhan', 'shahadat', 'zia', 'ziaur', 'mamun',
    
    # Native Bengali
    'শাহরিয়ার', 'শাহারিয়ার', 'ইমতিয়াজ', 'সৈয়দ', 'হাসান', 'হাছান', 'আহমেদ', 'আহমদ', 'ইয়াসির',
    'হোসেন', 'হোসাইন', 'হুসাইন', 'ইসলাম', 'রহমান', 'আলম', 'মাহমুদ', 'কবির',
    'রাকিব', 'সাকিব', 'শাকিল', 'তানভীর', 'তানভির', 'আরিফ', 'আশিক', 'নাঈম', 'শোয়েব',
    'জাহিদ', 'ইমরান', 'সোহেল', 'মেহেদী', 'মেহেদি', 'সুজন', 'সাব্বির', 'মনির', 'সায়েম',
    'মাসুদ', 'কামাল', 'রুবেল', 'ফয়সাল', 'ফয়সাল', 'এনামুল', 'মুশফিক', 'তামিম', 'মাহমুদুল্লাহ',
    'মুস্তাফিজ', 'তাসকিন', 'সৌম্য', 'লিটন', 'বিজয়', 'শান্ত', 'তৌহিদ', 'হৃদয়', 'শরিফুল',
    'এবাদত', 'খালেদ', 'নাসুম', 'মিরাজ', 'শহীদ', 'শাহীন', 'ইমন', 'মিজান', 'মিজানুর',
    'জাহাঙ্গীর', 'আনোয়ার', 'আলমগীর', 'হেলাল', 'দেলোয়ার', 'মোমিন', 'মোতালেব', 'আব্দুল',
    'আব্দুল্লাহ', 'আব্দুর', 'কাউসার', 'সাজ্জাদ', 'সাজিদ', 'সাদ', 'ফাহিম', 'নাহিদ', 'নাবিল',
    'শুভ', 'সুব্রত', 'জয়', 'দিপু', 'পলাশ', 'মিথুন', 'রাজীব', 'তারিক', 'শাফি', 'হাবিব',
    'হাবিবুর', 'সেলিম', 'সোলায়মান', 'সিদ্দিক', 'আশরাফ', 'আসাদ', 'আসিফ', 'রায়হান', 'আলভী',
    'ওয়াসিম', 'বাবু', 'খোকন', 'সুমন', 'জামিল', 'জাকির', 'মাকসুদ', 'বাপ্পি', 'সোহান',
    'সোহাগ', 'ফরিদ', 'হারুন', 'শরীফ', 'মারুফ', 'সিয়াম', 'ওমর', 'ওসমান', 'আলী', 'সাইফুল',
    'সিরাজ', 'জালাল', 'লতিফ', 'মান্নান', 'শফিক', 'তুষার', 'মাহবুব', 'ইকবাল', 'পারভেজ',
    'তামজিদ', 'মুর্শেদ', 'গোলাম', 'রাব্বি', 'ফারহান', 'শাহাদাত', 'জিয়া', 'মামুন'
}

# Unisex / Shared Family Title Tokens (Low gender weight: 0.5)
SHARED_SURNAME_TOKENS = {
    'khan', 'rana', 'chowdhury', 'talukder', 'talukdar', 'sarker', 'sarkar', 'sheikh',
    'kazi', 'miah', 'mia', 'mollah', 'bhuiyan', 'majumder', 'shikder', 'sikder', 'dewan',
    'khan', 'chaudhuri', 'khan', 'খান', 'রানা', 'চৌধুরী', 'তালুকদার', 'সরকার', 'শেখ',
    'কাজী', 'মিয়া', 'মোল্লা', 'ভূঁইয়া', 'মজুমদার', 'শিকদার', 'দেওয়ান'
}


def clean_name_tokens(name_str):
    """Normalize and tokenize customer name."""
    if not name_str:
        return []
    cleaned = re.sub(r'[^\w\s\.\u0980-\u09FF]', ' ', str(name_str).lower())
    tokens = [t.strip('.') for t in cleaned.split() if t.strip('.')]
    return tokens


def detect_gender_from_name(name_str):
    """
    Detect gender from customer name string.
    Returns: 'FEMALE', 'MALE', or 'UNKNOWN'
    """
    if not name_str or not isinstance(name_str, str):
        return 'UNKNOWN'

    tokens = clean_name_tokens(name_str)
    if not tokens:
        return 'UNKNOWN'

    # 1. Check strong prefixes / honorifics (First token)
    first_token = tokens[0]
    if first_token in FEMALE_PREFIXES:
        return 'FEMALE'
    if first_token in MALE_PREFIXES:
        return 'MALE'

    # 2. Score tokens against female & male dictionaries
    female_score = 0
    male_score = 0

    for i, token in enumerate(tokens):
        is_first_or_given = (i == 0 or (i == 1 and len(tokens) > 2))
        weight_multiplier = 1.5 if is_first_or_given else 1.0

        if token in FEMALE_PREFIXES:
            female_score += 4.0 * weight_multiplier
        elif token in FEMALE_NAME_TOKENS:
            female_score += 3.0 * weight_multiplier
        elif any(token.endswith(f) for f in ['khanam', 'khatun', 'begum', 'sultana', 'akter', 'aktar', 'আক্তার', 'খাতুন', 'খানম', 'বেগম', 'সুলতানা']):
            female_score += 3.0

        if token in MALE_PREFIXES:
            male_score += 4.0 * weight_multiplier
        elif token in MALE_NAME_TOKENS:
            male_score += 3.0 * weight_multiplier
        elif any(token.endswith(m) for m in ['uddin', 'ullah', 'uzzaman', 'উদ্দীন', 'উল্লাহ', 'উজ্জামান']):
            male_score += 3.0
            
        if token in SHARED_SURNAME_TOKENS:
            # Low male bias on surname alone if no female given name present
            male_score += 0.5

    # 3. Decision rule
    if female_score >= 2.0 and female_score > male_score:
        return 'FEMALE'
    elif male_score >= 2.0 and male_score > female_score:
        return 'MALE'

    # 4. Check specific prominent female name endings in Bengali naming conventions
    last_token = tokens[-1]
    if last_token in {'akter', 'aktar', 'khatun', 'khanam', 'begum', 'sultana', 'nesa', 'nahar', 'parvin', 'yasmin', 'আক্তার', 'খাতুন', 'খানম', 'বেগম', 'সুলতানা', 'নেছা', 'নাহার', 'পারভীন', 'ইয়াসমিন'}:
        return 'FEMALE'

    # Fallback to UNKNOWN
    return 'UNKNOWN'

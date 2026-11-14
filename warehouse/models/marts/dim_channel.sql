select * from (
    values
        ('paid_search',    'Paid search',    'paid',   true),
        ('paid_social',    'Paid social',    'paid',   true),
        ('organic_search', 'Organic search', 'earned', false),
        ('referral',       'Referral',       'earned', false),
        ('email',          'Email',          'owned',  false),
        ('direct',         'Direct',         'owned',  false)
) as t(channel_key, channel_name, channel_group, is_paid)

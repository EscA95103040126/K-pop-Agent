-- Sync kpop_items.gender_category with the confirmed artist-level grouping.
-- `all` is a user preference only; it is not stored as a kpop_items.gender_category.

update kpop_items
set gender_category = 'boy_group'
where artist in (
  'ATEEZ',
  'BOYNEXTDOOR',
  'BSS',
  'CRAVITY',
  'DAY6',
  'ENHYPEN',
  'EXO',
  'MONSTA X',
  'NCT 127',
  'NCT DREAM',
  'NCT U',
  'NCT WISH',
  'SEVENTEEN',
  'Stray Kids',
  'TXT',
  'ZEROBASEONE'
);

update kpop_items
set gender_category = 'girl_group'
where artist in (
  'aespa',
  'BABYMONSTER',
  'BLACKPINK',
  'H1-KEY',
  'Hearts2Hearts',
  'i-dle',
  '(G)I-DLE',
  'ILLIT',
  'IVE',
  'KISS OF LIFE',
  'LE SSERAFIM',
  'MEOVV',
  'QWER',
  'Red Velvet',
  'Red Velvet X aespa',
  'tripleS',
  'TWICE'
);

update kpop_items
set gender_category = 'mixed'
where artist = 'ALLDAY PROJECT';

select gender_category, count(*) as item_count
from kpop_items
group by gender_category
order by gender_category;

select artist, gender_category, count(*) as item_count
from kpop_items
where item_type = 'mv'
group by artist, gender_category
order by gender_category, artist;

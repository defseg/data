# I have a self-imposed deadline for this but something else just came up, so here be dragons. Sorry.
# The eventual plan is to have everything be in Haskell - this is only for v0.1.

import psycopg2
import pyglottolog
import os.path
from glob import glob
from collections import OrderedDict
import iphon_configparser
from commit import parse_phoneme, parse_allophonic_rule, validate, INI_DEFAULTS
from add import maybe

GLOTTOLOG_PATH = os.path.expanduser('~/Documents/glottolog-4.0')
glottolog = pyglottolog.Glottolog(GLOTTOLOG_PATH)

# Harmonize with Pshrimp for now; fix them both later.
DOCULECT_NAME_COL = 'language_name'
DOC_SEG_JOIN_TBL  = 'doculect_segments'
SEGMENT_COL       = 'phoneme'

schema = '''\
    languages (                                 \
        id SERIAL PRIMARY KEY,                  \
        name VARCHAR(255),                      \
        glottocode VARCHAR(255) NOT NULL,       \
        iso6393 VARCHAR(255),                   \
        family VARCHAR(255),                    \
        genus VARCHAR(255),                     \
        macroarea VARCHAR(255),                 \
        latitude FLOAT,                         \
        longitude FLOAT                         \
    )
    doculects (                                                  \
        id SERIAL PRIMARY KEY,                                   \
        inventory_id VARCHAR(255) NOT NULL,                      \
        {DOCULECT_NAME_COL} VARCHAR(255) NOT NULL,               \
        glottocode VARCHAR(255) NOT NULL,                        \
        dialect VARCHAR(255),                                    \
        dialect_name VARCHAR(255),                               \
                                                                 \
        notes TEXT,                                              \
                                                                 \
        source_bibkey VARCHAR(255),                              \
        source_url TEXT,                                         \
        source_author TEXT,                                      \
        source_doi VARCHAR(255),                                 \
        source_title VARCHAR(255),                               \
        source_publisher VARCHAR(255),                           \
        source_volume VARCHAR(255),                              \
        source_number VARCHAR(255),                              \
        source_year INTEGER,                                     \
        source_pages VARCHAR(255)                                \
    )                                   
    countries (                               \
        id VARCHAR(255) PRIMARY KEY,          \
        name VARCHAR(255) NOT NULL            \
    )
    languages_countries (                                  \
        language_id INTEGER NOT NULL,                      \
        country_id VARCHAR(255) NOT NULL,                  \
        FOREIGN KEY(language_id) REFERENCES languages(id), \
        FOREIGN KEY(country_id) REFERENCES countries(id),  \
        UNIQUE(language_id, country_id)                    \
    )
    segments (                                         \
        id SERIAL PRIMARY KEY,                         \
        {SEGMENT_COL} VARCHAR(255) NOT NULL,           \
        glyph_id VARCHAR(255),                         \
        segment_class VARCHAR(255) NOT NULL,           \
        tone VARCHAR(255) NOT NULL,                    \
        stress VARCHAR(255) NOT NULL,                  \
        syllabic VARCHAR(255) NOT NULL,                \
        short VARCHAR(255) NOT NULL,                   \
        long VARCHAR(255) NOT NULL,                    \
        consonantal VARCHAR(255) NOT NULL,             \
        sonorant VARCHAR(255) NOT NULL,                \
        continuant VARCHAR(255) NOT NULL,              \
        delayed_release VARCHAR(255) NOT NULL,         \
        approximant VARCHAR(255) NOT NULL,             \
        tap VARCHAR(255) NOT NULL,                     \
        trill VARCHAR(255) NOT NULL,                   \
        nasal VARCHAR(255) NOT NULL,                   \
        lateralis VARCHAR(255) NOT NULL,               \
        labial VARCHAR(255) NOT NULL,                  \
        round VARCHAR(255) NOT NULL,                   \
        labiodental VARCHAR(255) NOT NULL,             \
        coronal VARCHAR(255) NOT NULL,                 \
        anterior VARCHAR(255) NOT NULL,                \
        distributed VARCHAR(255) NOT NULL,             \
        strident VARCHAR(255) NOT NULL,                \
        dorsal VARCHAR(255) NOT NULL,                  \
        high VARCHAR(255) NOT NULL,                    \
        low VARCHAR(255) NOT NULL,                     \
        front VARCHAR(255) NOT NULL,                   \
        back VARCHAR(255) NOT NULL,                    \
        tense VARCHAR(255) NOT NULL,                   \
        retracted_tongue_root VARCHAR(255) NOT NULL,   \
        advanced_tongue_root VARCHAR(255) NOT NULL,    \
        periodic_glottal_source VARCHAR(255) NOT NULL, \
        epilaryngeal_source VARCHAR(255) NOT NULL,     \
        spread_glottis VARCHAR(255) NOT NULL,          \
        constricted_glottis VARCHAR(255) NOT NULL,     \
        fortis VARCHAR(255) NOT NULL,                  \
        ejective VARCHAR(255) NOT NULL,                \
        implosive VARCHAR(255) NOT NULL,               \
        click VARCHAR(255) NOT NULL                    \
    )
    {DOC_SEG_JOIN_TBL} (                                     \
        id SERIAL PRIMARY KEY,                               \
        doculect_id INTEGER NOT NULL,                        \
        segment_id INTEGER NOT NULL,                         \
        marginal BOOLEAN,                                    \
        loan BOOLEAN,                                        \
        FOREIGN KEY(doculect_id) REFERENCES doculects(id),   \
        FOREIGN KEY(segment_id) REFERENCES segments(id),     \
        UNIQUE (doculect_id, segment_id)                     \
    )
    allophones (                                                           \
        id SERIAL PRIMARY KEY,                                             \
        doculect_segment_id INTEGER NOT NULL,                              \
        allophone_id INTEGER NOT NULL,                                     \
        variation BOOLEAN NOT NULL,                                        \
        compound VARCHAR(255),                                             \
        environment VARCHAR(255),                                          \
        FOREIGN KEY(doculect_segment_id) REFERENCES {DOC_SEG_JOIN_TBL}(id),\
        FOREIGN KEY(allophone_id) REFERENCES segments(id)                  \
    )\
'''.format(DOCULECT_NAME_COL=DOCULECT_NAME_COL, SEGMENT_COL=SEGMENT_COL, DOC_SEG_JOIN_TBL=DOC_SEG_JOIN_TBL)

# -----------
# -- utils --
# -----------

def init_db():
    conn_string = "dbname=indexphonemica user=postgres password=postgres"
    conn = psycopg2.connect(conn_string)
    sql = conn.cursor()
    build_schema = [f'CREATE TABLE IF NOT EXISTS {table}' for table in schema.split('\n')]
    for t in build_schema:
        sql.execute(t)
    conn.commit()
    return (conn, sql)

def get_id(table, field, value, sql):
    '''Get (assumed to be unique) id of the thing in `table` where `field` = `value`. Returns False if it's not there.'''
    # NB: Passing table/column names as parameters doesn't work. This does not appear to be documented.
    sql.execute('SELECT id FROM {} WHERE {} = %s'.format(table, field), (value,))
    res = sql.fetchone()
    return res[0] if res else None

def insert(table, props, sql, return_id=True):
    '''Insert OrderedDict `props` ({col_name: prop}) into `table`.'''
    # ON CONFLICT REPLACE for allophones - looks like there's a lot of dups.
    s = 'INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING'.format(table, ','.join(props.keys()), ','.join([f'%({val})s' for val in props.keys()]))
    if return_id:
        s += ' RETURNING id'
    sql.execute(s, props)

def dfilter(d, keys):
    '''Return a new OrderedDict consisting of only the key/value pairs in dict d with keys listed in the `keys` set.
    Also munge them so they fit nicely in the DB.'''
    return OrderedDict((munge_key(k), munge_value(v)) for k, v in d.items() if munge_key(k) in keys)

def dinsert(table, d, keys, sql):
    '''dfilter, then insert'''
    insert(table, dfilter(d, keys), sql = sql)

# ----------------------
# -- import doculects --
# ----------------------

def read_ini(path, sql):
    ini = iphon_configparser.parser()
    ini.read(path, encoding='utf-8')

    validate(ini)

    doculect = OrderedDict()

    doculect['inventory_id'] = os.path.split(path)[-1][:-4] # get the filename minus the .ini
    
    doculect[DOCULECT_NAME_COL] = ini['core']['name']
    doculect['glottocode']      = ini['core']['glottocode']
    doculect['dialect']         = maybe(ini['core'], 'dialect')
    doculect['dialect_name']    = maybe(ini['core'], 'dialect_name')

    doculect['notes'] = '\n'.join(maybe(ini, 'notes', []))
    if doculect['notes'] == '':
        doculect['notes'] = None

    doculect['source_bibkey']    = maybe(ini['source'], 'glottolog', filters=INI_DEFAULTS)
    doculect['source_url']       = maybe(ini['source'], 'url', filters=INI_DEFAULTS)
    doculect['source_author']    = maybe(ini['source'], 'author', filters=INI_DEFAULTS)
    doculect['source_title']     = maybe(ini['source'], 'title', filters=INI_DEFAULTS)
    doculect['source_publisher'] = maybe(ini['source'], 'publisher', filters=INI_DEFAULTS)
    doculect['source_volume']    = maybe(ini['source'], 'volume', filters=INI_DEFAULTS)
    doculect['source_number']    = maybe(ini['source'], 'number', filters=INI_DEFAULTS)
    doculect['source_year']      = maybe(ini['source'], 'year', filters=INI_DEFAULTS)
    doculect['source_pages']     = maybe(ini['source'], 'pages', filters=INI_DEFAULTS)
    doculect['source_doi']       = maybe(ini['source'], 'doi', filters=INI_DEFAULTS)

    if doculect['source_year'] == 'Unknown':
        doculect['source_year'] = None

    phonemes = list(ini['phonemes'])
    allophonic_rules = [parse_allophonic_rule(a) for a in ini['allophonic_rules']]

    # Start writing - first the doculect...
    insert('doculects', doculect, return_id=True, sql=sql)
    doculect_id = sql.fetchone()[0]
    # ...then the language, if necessary...
    language_id = find_or_create_language(doculect['glottocode'], sql=sql)
    # ...then the segments... 
    # We'll handle featuralization later.
    # We'll also figure out how to store alternate forms later;
    # for now, we'll mostly mirror PSMITH's db structure,
    # and store non-canonical forms (that aren't listed as allophones) as conditionless allophonic rules.
    # (The eventual goal is to have everything in Haskell, so this is good enough for v0.1,
    # but it's not strictly correct.)
    # Another thing we'll figure out later is phoneme junctions in allophonic rules - 
    # e.g. s+i > s̩ / unstressed.
    # These will be stored as:
    # s > s̩ / unstressed (_+i)
    # i > s̩ / unstressed (s+_)
    # Which also isn't strictly correct, but isn't good enough.
    # Rules with + in the output are just ignored, because I don't know how they should be handled, and see above re: deadlines.
    # Maybe we want NoSQL for the final DB.

    doculect_segment_ids = {}
    for phoneme_txt in phonemes:
        phoneme = parse_phoneme(phoneme_txt)
        canonical_form_id = find_or_create_segment(phoneme['canonical_form'], sql=sql)
        noncanonical_forms = phoneme['noncanonical_forms']
        # OK, let's just do this as string processing to ensure consistency
        form_rule_str = '{} > {} / (non-canonical form - i.e. alternate representation of the phoneme)'
        form_rules = [parse_allophonic_rule(form_rule_str.format(phoneme['canonical_form'], noncanonical_form)) for noncanonical_form in noncanonical_forms]
        allophonic_rules += form_rules

        # Then build the doculect_segments, and save them in a mapping of phoneme -> doculect_segment_id for this doculect.
        insert(DOC_SEG_JOIN_TBL, OrderedDict({
            'doculect_id': doculect_id
        ,   'segment_id' : canonical_form_id
        ,   'marginal'   : phoneme['marginal']
        ,   'loan'       : phoneme['loan']
        }), return_id=True, sql=sql)
        doculect_segment_ids[phoneme['canonical_form']] = sql.fetchone()[0]

    # ...then the allophones...
    for allophonic_rule in allophonic_rules:
        serialized_rules = []
        # Note that 'variation' refers to whether the rule itself is obligatory or optional,
        # not whether there's variance in outputs (all of which are distinct from the input) of the rule.
        # That is, the presence of variation means the rule may output its input,
        # and the absence of variation means it may not.
        # That's the ideal, anyway. What +variation means here *in practice* is the presence of a ~ right after the >.

        for allophone in allophonic_rule['allophones']:
            # Skip anything with + in the output because we can't handle that in v0.1
            if '+' in allophone:
                continue

            allophone_segment_id = find_or_create_segment(allophone, sql=sql)
            
            # If it's a compound, store the whole compound as text, I guess.
            compound = None
            if len(allophonic_rule['phonemes']) > 1:
                compound = '+'.join(allophonic_rule['phonemes'])
            
            for phoneme in allophonic_rule['phonemes']:
                rule = OrderedDict({
                    'doculect_segment_id': doculect_segment_ids[phoneme]
                ,   'allophone_id':        allophone_segment_id
                ,   'variation':           allophonic_rule['rule_type'] == 'variant'
                ,   'compound':            '+'.join(allophonic_rule['phonemes']) if len(allophonic_rule['phonemes']) > 1 else None
                ,   'environment':         allophonic_rule['environment']
                })
                insert('allophones', rule, sql=sql)

def find_or_create_segment(segment, sql):
    segment_id = get_id('segments', SEGMENT_COL, segment, sql=sql)
    if not segment_id:
        insert('segments', OrderedDict({SEGMENT_COL: segment}), return_id=True, sql=sql)
        segment_id = sql.fetchone()[0]
    return segment_id

def find_or_create_language(glottocode, sql):
    '''Get language info, or create it from Glottolog. Returns the ID of the language.
    Also creates country and language_country info.'''
    id = get_id('languages', 'glottocode', glottocode, sql=sql)
    if id:
        return id

    g_languoid = glottolog.languoid(glottocode)

    language = OrderedDict()

    # Genus: next level below top-level family if it exists.
    # If it's in a family but in the top level, make it the same as the family.
    # If it's an isolate, 'Isolate'.

    genus = 'Isolate'
    if g_languoid.family:
        genus = g_languoid.lineage[0][0]
    if len(g_languoid.lineage) > 1:
        genus = g_languoid.lineage[1][0]

    # sometimes this is blank
    family = 'Unknown'
    if g_languoid.family:
        family = g_languoid.family.name

    language['name']       = g_languoid.name
    language['glottocode'] = glottocode 
    language['iso6393']    = g_languoid.iso           # are .iso and .iso_code the same?
    language['family']     = family
    language['genus']      = genus # note that .lineage returns (name, glottocode, <family>) - we'll only store the name for now; easier to search
    language['macroarea']  = g_languoid.macroareas[0].value # English only has Eurasia, so I assume these only have one
    language['latitude']   = g_languoid.latitude
    language['longitude']  = g_languoid.longitude

    insert('languages', language, return_id=True, sql=sql)
    language_id = sql.fetchone()[0]

    # country stuff
    for country in g_languoid.countries:
        country_id = get_id('countries', 'id', country.id, sql=sql)
        if not country_id:
            insert('countries', OrderedDict({'id': country.id, 'name': country.name}), sql=sql)
            country_id = sql.fetchone()[0] # `insert` returns an ID; this is how we get it
        insert('languages_countries', OrderedDict({
            'language_id': language_id,
            'country_id':  country_id
            }), return_id=False, sql=sql) # these don't have IDs so don't try to return one

    return language_id

# don't save anything if something crashes - this way we don't have to drop the whole DB before trying again
def go():
    conn, sql = init_db()

    files = glob('doculects/*.ini')
    for file in files:
        print(file)
        read_ini(file, sql=sql)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    go()
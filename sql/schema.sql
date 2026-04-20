CREATE SCHEMA lab_data;

-- Sites table
CREATE TABLE lab_data.sampling_sites (
    site_name TEXT PRIMARY KEY,
    country TEXT NOT NULL DEFAULT 'Poland',
    region TEXT,
    county TEXT
);

-- Individuals table
CREATE TABLE lab_data.individuals (
    lab_id TEXT PRIMARY KEY,
    grave_no TEXT,
    project_id TEXT,
    date_ce_start INTEGER,
    date_ce_stop INTEGER,
    epoch TEXT,
    site_name TEXT NOT NULL REFERENCES lab_data.sampling_sites(site_name) ON UPDATE CASCADE
);

-- Processed samples table
CREATE TABLE lab_data.processed_samples (
    lab_id TEXT NOT NULL REFERENCES lab_data.individuals(lab_id) ON UPDATE CASCADE,
    material TEXT NOT NULL,
    prep_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prep_operator TEXT NOT NULL,
    lysis_method TEXT DEFAULT 'Rohland et al. 2018',

    -- The Primary key will be the combination of lab_id and material (ex: PL626 T)
    UNIQUE (lab_id, material), -- Avoids duplicates
    PRIMARY KEY (lab_id, material)
);


CREATE TABLE lab_data.dna_extractions (
    lab_id TEXT NOT NULL,
    material TEXT NOT NULL,
    times_extracted INTEGER NOT NULL,
    extract_operator TEXT,
    extract_date DATE,
    extract_method TEXT NOT NULL DEFAULT 'Rohland et al. 2018',
    extract_remarks TEXT,
    UDG_treatment TEXT,
    UDG_date TEXT,
    UDG_method TEXT,
    UDG_remarks TEXT,


    FOREIGN KEY (lab_id, material)
        REFERENCES lab_data.processed_samples(lab_id, material) 
        ON UPDATE CASCADE,

    PRIMARY KEY (lab_id, material, times_extracted)
);


CREATE TABLE lab_data.libraries (
    library_id TEXT PRIMARY KEY,
    lab_id TEXT NOT NULL,
    material TEXT NOT NULL,
    times_extracted INTEGER NOT NULL,
    library_type TEXT NOT NULL DEFAULT 'Single',
    library1_date DATE,
    library_operator TEXT,
    library_remarks TEXT,

    elution_date DATE,
    elution_operator TEXT,
    elution_remarks TEXT,

    FOREIGN KEY (lab_id, material, times_extracted)
        REFERENCES lab_data.dna_extractions(lab_id, material, times_extracted)
        ON UPDATE CASCADE
);

CREATE TABLE lab_data.sequencing_run (
    sequencing_id TEXT PRIMARY KEY,
    sequencing_date DATE
);

CREATE TABLE lab_data.sequencing_libraries(
    library_id TEXT NOT NULL,
    sequencing_id TEXT NOT NULL,

    FOREIGN KEY (library_id)
        REFERENCES lab_data.libraries(library_id)
        ON UPDATE CASCADE,
    FOREIGN KEY (sequencing_id)
        REFERENCES lab_data.sequencing_run(sequencing_id)
        ON UPDATE CASCADE,

    PRIMARY KEY (library_id, sequencing_id)
);

CREATE TABLE lab_data.indexing (
    library_id TEXT NOT NULL,
    sequencing_id TEXT NOT NULL,

    index_used TEXT,
    index_date DATE,
    index_operator TEXT,
    index_method TEXT DEFAULT 'Cx, XX ul',
    index_remarks TEXT,

    library_concentration FLOAT,
    qPCR_date DATE,
    qPCR_operator TEXT,
    qPCR_method TEXT DEFAULT 'AA Biotech',
    log_onset INTEGER,
    qPCR_remarks TEXT,

    FOREIGN KEY (library_id, sequencing_id)
        REFERENCES lab_data.sequencing_libraries(library_id, sequencing_id)
        ON UPDATE CASCADE,

    PRIMARY KEY (library_id, sequencing_id)
);

CREATE TABLE lab_data.dna_sequencing (
    fastq_name TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    sequencing_id TEXT NOT NULL,

    index_p7 TEXT,
    index_P5 TEXT,
    fastq_path TEXT,
    raw_reads INTEGER,
    shotgun_enriched TEXT DEFAULT 'No',
    suffix1 TEXT,
    suffix2 TEXT,
    suffix3 TEXT,
    suffix4 TEXT,
    suffix5 TEXT,


    FOREIGN KEY (library_id, sequencing_id)
        REFERENCES lab_data.sequencing_libraries(library_id, sequencing_id)
        ON UPDATE CASCADE
);

CREATE TABLE lab_data.dna_mapping (
    bam_path TEXT PRIMARY KEY,
    fastq_name TEXT NOT NULL,
    merged TEXT DEFAULT 'No',
    tot_reads_map INTEGER,
    unique_reads_map INTEGER,
    endo_dna FLOAT,

    FOREIGN KEY (fastq_name)
        REFERENCES lab_data.dna_sequencing(fastq_name)
        ON UPDATE CASCADE

);

CREATE TABLE lab_data.sex_estimation (
    fastq_name TEXT NOT NULL,
    rx FLOAT,
    ci_low_95 FLOAT,
    ci_high_95 FLOAT,
    assignment TEXT,
    assignment_min_10k_reads TEXT,

    FOREIGN KEY (fastq_name)
        REFERENCES lab_data.dna_sequencing(fastq_name)
        ON UPDATE CASCADE,

    PRIMARY KEY (fastq_name)
);


-- Quickly check samples status
CREATE VIEW lab_data.individuals_status AS
SELECT 
    -- 1. Identification (full_sample_id puts together the lab_id (ex: PL626) and material (ex: T))
    i.lab_id, 

    STRING_AGG(DISTINCT ps.material, ', ') AS processed_materials,
    STRING_AGG(DISTINCT ps.prep_date::TEXT, ' |') AS processing_dates,

    -- 2. Counting the number of extractions and sequencing
    COUNT(DISTINCT de.times_extracted) AS num_extractions,
    COUNT(DISTINCT sl.sequencing_id) AS times_sequenced,

    -- 3. Info extractions (grouped in one line in case of multiple extractions)
    STRING_AGG(DISTINCT de.extract_date::TEXT, ' | ') AS extract_dates,
    STRING_AGG(DISTINCT de.UDG_date::TEXT, ' | ') AS udg_dates,

    -- 4. Info library
    STRING_AGG(DISTINCT lib.library_id, ', ') AS library_ids,
    STRING_AGG(DISTINCT lib.library1_date::TEXT, ' | ') AS library_dates,
    STRING_AGG(DISTINCT lib.elution_date::TEXT, ' | ') AS elution_dates,

    -- 5. Info indexing
    STRING_AGG(DISTINCT ix.index_date::TEXT, ' | ') AS index_dates,
    STRING_AGG(DISTINCT ix.qPCR_date::TEXT, ' | ') AS qPCR_dates,

    -- 6. Info sequencing
    STRING_AGG(DISTINCT sr.sequencing_date::TEXT, ' | ') AS sequencing_run_dates,

    -- 7. Info fastq, mapping and sex
    STRING_AGG(DISTINCT ds.fastq_path, ', ') AS fastq_files,
    STRING_AGG(DISTINCT ds.raw_reads::TEXT, ', ') AS raw_reads_info,
    STRING_AGG(DISTINCT dm.tot_reads_map::TEXT, ', ') AS mapped_reads_info,
    STRING_AGG(DISTINCT dm.endo_dna::TEXT, ', ') AS endo_dna_info,
    STRING_AGG(DISTINCT se.assignment::TEXT, ', ') AS sex_info

FROM lab_data.individuals i

LEFT JOIN lab_data.processed_samples ps 
    ON i.lab_id = ps.lab_id

LEFT JOIN lab_data.dna_extractions de 
    ON ps.lab_id = de.lab_id AND ps.material = de.material

LEFT JOIN lab_data.libraries lib 
    ON de.lab_id = lib.lab_id AND de.material = lib.material AND de.times_extracted = lib.times_extracted

LEFT JOIN lab_data.sequencing_libraries sl 
    ON lib.library_id = sl.library_id

LEFT JOIN lab_data.indexing ix 
    ON sl.library_id = ix.library_id AND sl.sequencing_id = ix.sequencing_id

LEFT JOIN lab_data.sequencing_run sr 
    ON sl.sequencing_id = sr.sequencing_id

LEFT JOIN lab_data.dna_sequencing ds 
    ON sl.library_id = ds.library_id AND sl.sequencing_id = ds.sequencing_id

LEFT JOIN lab_data.dna_mapping dm 
    ON ds.fastq_name = dm.fastq_name

LEFT JOIN lab_data.sex_estimation se 
    ON ds.fastq_name = se.fastq_name

GROUP BY i.lab_id;
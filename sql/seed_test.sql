-- 1. Insert a site
INSERT INTO lab_data.sampling_sites (site_name, country) 
VALUES ('Imaginary Land', 'Poland');

-- 2. Insert an individual
INSERT INTO lab_data.individuals (lab_id, site_name, project_id) 
VALUES ('PL001', 'Imaginary Land', 'Project-test');

-- 3. 2 samples for the same individual
INSERT INTO lab_data.processed_samples (lab_id, material, prep_operator, prep_date) 
VALUES ('PL001', 'T', 'FL', '2024-04-20'),
       ('PL001', 'A', 'FL', '2024-04-24');

-- 4. 2 extractions for the tooth
INSERT INTO lab_data.dna_extractions (lab_id, material, times_extracted, extract_date) 
VALUES ('PL001', 'T', 1, '2024-05-01'),
       ('PL001', 'T', 2, '2024-05-10');

-- 5. Library for the first extraction
INSERT INTO lab_data.libraries (library_id, lab_id, material, times_extracted, library_operator, library1_date, elution_date)
VALUES ('LIB_PL001_T1', 'PL001', 'T', 1, 'MM', '2024-05-14', '2024-05-15');

INSERT INTO lab_data.indexing(library_id, sequencing_id, index_date, qPCR_date)
VALUES ('LIB_P1_T1', 'NR102SS', '2024-05-17', '2024-05-18'),
        ('LIB_P1_T1', 'NR103SS', '2024-05-22', '2024-05-23');

INSERT INTO lab_data.sequencing_run(sequencing_id, sequencing_date)
VALUES ('NR102SS', '2024-05-20'),
        ('NR103SS', '2024-05-25');

INSERT INTO lab_data.sequencing_libraries(sequencing_id, library_id)
VALUES ('NR102SS', 'LIB_P1_T1'),
        ('NR103SS', 'LIB_P1_T1');
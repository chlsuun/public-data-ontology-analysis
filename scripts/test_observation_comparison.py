"""Check joins, unit semantics, metadata exclusions, and independently recompute metrics."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import numpy as np
import openpyxl
from analyze_observation_comparison import indexed, to_persons, pearson, parse_oecd, parse_worldbank

FOLDER = Path(__file__).resolve().parents[1] / "analysis/observation-comparison/20260915"


class ObservationTests(unittest.TestCase):
    def test_unit_missing_and_duplicate_semantics(self):
        self.assertEqual(to_persons('51.751065',6),51751065)
        self.assertEqual(to_persons('123.4',3),123400)
        self.assertIsNone(to_persons(None,0))
        for bad in ['NaN','Infinity','-1','0']:
            with self.assertRaises(ValueError):to_persons(bad,0)
        with self.assertRaises(ValueError):
            indexed([{'country':'KOR','year':2020},{'country':'KOR','year':2020}])
        with self.assertRaises(ValueError):indexed([{'country':'XXX','year':2020}])
        self.assertIsNone(pearson([1,1,1],[1,2,3]))

    def test_independent_raw_reconciliation(self):
        d=json.loads((FOLDER/'result.json').read_text(encoding='utf-8'))
        # Independent extraction bypasses production parsers and the normalized file.
        ns={'g':'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic'}
        root=ET.parse(FOLDER/'raw/oecd-population.xml').getroot()
        a={}
        for obs in root.findall('.//g:Obs',ns):
            kv={x.attrib['id']:x.attrib['value'] for x in obs.findall('.//g:Value',ns)}
            a[(kv['REF_AREA'],int(kv['TIME_PERIOD']))]=float(obs.find('g:ObsValue',ns).attrib['value'])*10**int(kv['UNIT_MULT'])
        wb=json.loads((FOLDER/'raw/worldbank-population.json').read_text())[1]
        b={(x['countryiso3code'],int(x['date'])):x['value'] for x in wb}
        self.assertEqual(len(a),60);self.assertEqual(len(b),60)
        for r in d['pairs']:
            k=(r['country'],r['year'])
            self.assertEqual(r['oecd'],a[k]);self.assertEqual(r['worldbank'],b[k])
            self.assertAlmostEqual(r['difference_pct'],(a[k]-b[k])/b[k]*100,places=11)
        for c,s in d['country_summaries'].items():
            for mode in ['all','sensitivity']:
                rows=[r for r in d['pairs'] if r['country']==c and (mode=='all' or r['sensitivity_included'])]
                ar=np.array([a[(c,r['year'])] for r in rows]);br=np.array([b[(c,r['year'])] for r in rows])
                z=s[mode]
                self.assertAlmostEqual(z['mean_absolute_gap_pct'],float(np.mean(np.abs((ar-br)/br*100))),places=11)
                self.assertAlmostEqual(z['mae_persons'],float(np.mean(np.abs(ar-br))),places=8)
                self.assertAlmostEqual(z['level_pearson_r'],float(np.corrcoef(ar,br)[0,1]),places=11)
                years={r['year'] for r in rows}
                intervals=[y for y in sorted(years) if y-1 in years]
                self.assertEqual(z['change_n'],len(intervals))
                ad=np.array([a[(c,y)]-a[(c,y-1)] for y in intervals]);bd=np.array([b[(c,y)]-b[(c,y-1)] for y in intervals])
                self.assertAlmostEqual(z['change_pearson_r'],float(np.corrcoef(ad,bd)[0,1]),places=11)
        self.assertEqual(a['DEU',2022]-b['DEU',2022],620174)

    def test_metadata_exclusions_and_evidence(self):
        d=json.loads((FOLDER/'result.json').read_text(encoding='utf-8'))
        excluded={(r['country'],r['year']) for r in d['pairs'] if not r['sensitivity_included']}
        self.assertEqual(excluded,{('JPN',2024),('DEU',2011),('DEU',2022),('DEU',2023),('DEU',2024)})
        workbook=openpyxl.load_workbook(FOLDER/'raw/oecd-country-metadata.xlsx',read_only=True,data_only=True)
        extracts=json.loads((FOLDER/'oecd-country-metadata-extract.json').read_text(encoding='utf-8'))
        for row in extracts:
            for cell,value in row['cells'].items():self.assertEqual(workbook[row['sheet']][cell].value,value)
        self.assertIn('October',workbook['Sources']['F32'].value)
        for receipt in d['receipts']:
            body=(FOLDER/'raw'/receipt['file']).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(),receipt['sha256'])
        self.assertEqual(d['relationship']['status'],'analysis_completed_pending_human_review')
        self.assertFalse(d['relationship']['model_json_modified'])


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ObservationTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    from datetime import datetime,timezone
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful(),
            'coverage':['unit scaling and missing/invalid values','duplicate and unexpected key rejection',
                        'independent raw XML/JSON values for all 60 pairs','NumPy comparison of all country metrics',
                        'consecutive-year intervals after exclusions','country metadata cells against unchanged XLSX',
                        'all download SHA-256 receipts','human approval remains pending'],
            'script_sha256':{p:hashlib.sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in
                             ['analyze_observation_comparison.py','render_observation_comparison.py','test_observation_comparison.py']}}
    (FOLDER/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)

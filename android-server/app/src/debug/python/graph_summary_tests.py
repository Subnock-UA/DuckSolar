import unittest
from datetime import datetime,date,timedelta
from unittest.mock import patch
import graph_energy_tests as baseline

class GraphSummary(unittest.TestCase):
 setUp=baseline.GraphEnergyTest.setUp
 tearDown=baseline.GraphEnergyTest.tearDown
 append=baseline.GraphEnergyTest.append
 def populate(self):
  start=datetime(2026,10,13,12,tzinfo=baseline.ZONE)
  for i in range(130):self.append(start+timedelta(minutes=i*5),1000+i*10)
 def test_power_summary_uses_full_data_before_reduction(self):
  self.populate()
  power=self.view.graph_data('day',date(2026,10,13),'Local',['pv_w','output_w'],max_points=100)
  energy=self.view.graph_data('day',date(2026,10,13),'Local',mode='energy')
  self.assertEqual(power['energy_summary'],energy['energy_summary'])
  self.assertEqual(power['kind'],'line');self.assertLessEqual(len(power['points']),100)
 def test_month_power_summary_matches_energy_without_daily_reports(self):
  self.populate()
  with patch('ducksolar.energy_streaming.MonthAccounting.report',side_effect=AssertionError('No daily balance')):
   power=self.view.graph_data('month',date(2026,10,1),'Local',['pv_w','output_w'])
   for fields in (['pv_w','output_w'],['grid_import_w','grid_export_w'],['pv_w','output_w','grid_import_w','grid_export_w']):
    energy=self.view.graph_data('month',date(2026,10,1),'Local',fields,mode='energy')
    self.assertEqual(power['energy_summary'],energy['energy_summary'])
 def test_other_instantaneous_parameters_do_not_launch_balance(self):
  self.populate()
  result=self.view.graph_data('day',date(2026,10,13),'Local',['battery_v'])
  self.assertNotIn('energy_summary',result)

if __name__=='__main__':unittest.main()

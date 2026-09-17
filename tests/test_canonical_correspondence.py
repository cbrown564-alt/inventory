from evals.synthetic.score_canonical_correspondence import _agreement, canonical_key
from homeinventory.compare import _norm_name

def test_safe_synonyms_collapse():
    assert canonical_key("Pedestal basin")=="type:basin"
    assert canonical_key("Wash basin")=="type:basin"
    assert canonical_key("Cooker hood")==canonical_key("Extractor hood")
def test_unknowns_do_not_collapse():
    assert canonical_key("Mystery object alpha")!=canonical_key("Mystery object beta")
def test_canonical_agreement_removes_vocabulary_churn():
    a=["Pedestal basin","Cooker hood","Waste bin"]; b=["Wash basin","Extractor hood","Waste bin"]
    assert _agreement(a,b,_norm_name)["agreement"]<100
    assert _agreement(a,b,canonical_key)["agreement"]==100
def test_multiset_preserves_repeat_disagreement():
    m=_agreement(["Dining chair"]*4,["Chair"]*3,canonical_key)
    assert (m["both"],m["either"],m["agreement"],m["churn"])==(3,4,75.0,1)
def test_materially_different_types_stay_distinct():
    assert canonical_key("Bread bin")!=canonical_key("Waste bin")
    assert canonical_key("Door")!=canonical_key("Door handle")

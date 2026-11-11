from welp_next.calibration_checks import acceptance

def extra_checks(record, transcript, workspace, fixture):
    return acceptance(record, transcript, workspace, fixture)

"""value_parser 单元测试。"""

import pytest

from src.parser.value_parser import parse_value, value_to_device_type


class TestParseCapacitor:
    """电容值解析。"""

    def test_pf_integer(self):
        result = parse_value("CAP_MIM", "1pF")
        assert result == {"capacitance_pf": 1.0}

    def test_pf_float(self):
        result = parse_value("CAP_MIM", "2.5pF")
        assert result == {"capacitance_pf": 2.5}

    def test_pf_zero(self):
        result = parse_value("CAP_MIM", "0pF")
        assert result == {"capacitance_pf": 0.0}

    def test_ff_to_pf(self):
        result = parse_value("CAP_MIM", "500fF")
        assert result == {"capacitance_pf": 0.5}

    def test_ff_integer(self):
        result = parse_value("CAP_MIM", "1000fF")
        assert result == {"capacitance_pf": 1.0}

    def test_case_insensitive(self):
        result = parse_value("CAP_MIM", "1PF")
        assert result == {"capacitance_pf": 1.0}

    def test_space_allowed(self):
        result = parse_value("CAP_MIM", "2.5 pF")
        assert result == {"capacitance_pf": 2.5}

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="无法解析电容值"):
            parse_value("CAP_MIM", "1uF")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_value("CAP_MIM", "")


class TestParseInductor:
    """电感值解析。"""

    def test_nh_integer(self):
        result = parse_value("IND_SPIRAL", "1nH")
        assert result == {"inductance_nH": 1.0}

    def test_nh_float(self):
        result = parse_value("IND_SPIRAL", "2.5nH")
        assert result == {"inductance_nH": 2.5}

    def test_case_insensitive(self):
        result = parse_value("IND_SPIRAL", "5NH")
        assert result == {"inductance_nH": 5.0}

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="无法解析电感值"):
            parse_value("IND_SPIRAL", "1uH")


class TestParseTransmissionLine:
    """传输线值解析。"""

    def test_slash_separator(self):
        result = parse_value("TL_MICROSTRIP", "50Ohm/1000um")
        assert result == {"impedance_ohm": 50.0, "length_um": 1000.0}

    def test_underscore_separator(self):
        result = parse_value("TL_MICROSTRIP", "50Ohm_2000um")
        assert result == {"impedance_ohm": 50.0, "length_um": 2000.0}

    def test_float_values(self):
        result = parse_value("TL_MICROSTRIP", "25.5Ohm/500.5um")
        assert result == {"impedance_ohm": 25.5, "length_um": 500.5}

    def test_case_insensitive(self):
        result = parse_value("TL_MICROSTRIP", "50ohm/1000UM")
        assert result == {"impedance_ohm": 50.0, "length_um": 1000.0}

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="无法解析传输线值"):
            parse_value("TL_MICROSTRIP", "50Ohm")


class TestValueToDeviceType:
    """part_name → device_type 映射。"""

    def test_capacitor(self):
        assert value_to_device_type("CAP_MIM") == "capacitor_mim"

    def test_inductor(self):
        assert value_to_device_type("IND_SPIRAL") == "inductor_spiral"

    def test_transmission_line(self):
        assert value_to_device_type("TL_MICROSTRIP") == "transmission_line"

    def test_unknown_type(self):
        with pytest.raises(ValueError, match="未知的器件类型"):
            value_to_device_type("RESISTOR")


class TestParseValueUnknownType:
    """不支持的器件类型。"""

    def test_raises_for_unknown(self):
        with pytest.raises(ValueError, match="不支持的器件类型"):
            parse_value("UNKNOWN", "1pF")

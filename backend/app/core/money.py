"""Money is always integer paise (₹1 = 100). Never floats."""


def fmt_inr(paise: int) -> str:
    """₹ with Indian digit grouping, for messages: 45716000 -> '₹4,57,160.00'."""
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}.{p:02d}"

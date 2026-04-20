import base64, zlib, json

sc = 'AAADdXictVJLSwMxEL4X+h/Cnqush9rHTdCTj4P1pEiYZsduIJuEmVnrUvrfJZtKK4gWpKeB7zHfhHyb4UCpgpHekbSYqJ1lQY+kYyAp5mo2KcvRoaitjhClTdYLkgf366Y/RbVI/CKn5fQ76aHBYq6K5y7WFM4WPVpkSQMfOjrokDhZM2g645JDqMWMgHNhjZU2QNy/S7+1zhVz9ZJopTZ5JC/sAyMho+jL2XipGzS1vsipvXAJzgGng8s9SMhC1kighJ+XmdiOjkiZjOX0ISuB5vQpHMl6WQn8LyqN1/x/FdnUhAjM60BVytoVgCMaAQk/klA11v9ESBf7g+9bJzb3J9fqzrIskNkG/9RF1I9XD7c31zsXeqEu1yeC1Af7CLl1wnt4ONh+AqVw+yw='
sd = 'AAACunicdZJBT8JAEIXvJPyHyZ45ACpRbpWQSqKGQBOPm6Ed2tV2t9lOkcb4383uglSNx5153+x7k/kYDgBEjhVJ7moScxAxVvRkMkq6muR6Ey2S1WIpRl5IB9Is5vDhXgCCLaZvDrq3qLMGHpDTImgBRImdaZ1cxOvvoh8hNVbhszUkqiKImN2kUX+uLEnnXDjZ1d1kJlzv8+TjWBvL8rUxWsxhj2VDo0uS1Oi9yns2a4spq5Rk1lpk5aGr8Xj0u82qImn2MsPuQgOIjtCKOUzH0+sTAyAqo72520spcJObS6UwrSMnsx6ndMsu/Pl/ANFQanT2s+bNVG3Jqi4V+SmhF3bQ920OZL38HRUrnUtNR5YNNU3IOvkbtcKjV0s2cmeOXtRb8DshF2T/HMWWSkrdBl+CwB/J4nEZbU4XcgZ3VOBBhfT/0vdnkdwmUbJanGYorVhhKXOraoevwju2qpbxZrl8FsPB5xdWJsgY'

for label, b64 in [('SERVERCONFIG', sc), ('SEASONDEFINITION', sd)]:
    raw = base64.b64decode(b64)
    header = raw[:4].hex()
    try:
        payload = zlib.decompress(raw[4:])
        data = json.loads(payload)
        print(f'\n=== {label} (header bytes: {header}) ===')
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f'{label} ERROR (header={header}): {e}')

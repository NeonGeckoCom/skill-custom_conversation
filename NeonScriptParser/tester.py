from script_parser import ScriptParser
import logging

fmt = '%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s'
logging.basicConfig(level=logging.DEBUG, format=fmt, datefmt='%Y-%m-%d:%H:%M:%S')

parser = ScriptParser()
parser.parse_script_to_file("examples/test.txt")
parser.parse_script_to_file("examples/test.txt", "examples/test.out")


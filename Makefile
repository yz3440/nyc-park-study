CXX = g++
CXXFLAGS = -std=c++17 -Wall
GEOS_PREFIX = /opt/homebrew/opt/geos
INCLUDES = -I$(GEOS_PREFIX)/include
LIBS = -L$(GEOS_PREFIX)/lib -lgeos

TARGET = build/1a_concave_hull
SOURCES = 1a_concave_hull.cpp

all: $(TARGET)

$(TARGET): $(SOURCES)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $(TARGET) $(SOURCES) $(LIBS)

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(TARGET)

.PHONY: all run clean


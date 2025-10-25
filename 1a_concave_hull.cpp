/*
 * Reads a GeoJSON file with MultiPolygon features and creates a new GeoJSON
 * where each feature's geometry is replaced with the concave hull of all
 * polygons in the MultiPolygon.
 */

#define GEOS_USE_ONLY_R_API
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <set>
#include <vector>

/* For geometry operations */
#include <geos/geom/GeometryFactory.h>
#include <geos/geom/Geometry.h>
#include <geos/geom/MultiPolygon.h>
#include <geos/geom/Polygon.h>

/* For GeoJSON read/write */
#include <geos/io/GeoJSONReader.h>
#include <geos/io/GeoJSONWriter.h>

/* For concave hull */
#include <geos/algorithm/hull/ConcaveHullOfPolygons.h>

/* For directory creation */
#if __cplusplus >= 201703L
#include <filesystem>
#else
#include <sys/stat.h>
#include <sys/types.h>
#endif

/* Geometry/GeometryFactory */
using namespace geos::geom;

/* GeoJSON I/O */
using namespace geos::io;

/* Concave hull */
using namespace geos::algorithm::hull;

const char *SOURCE_DATA_FILE = "./output_data/0b_parks_filtered.geojson";
const char *OUTPUT_PATH_HULLS = "./output_data/1a_parks_concave_hulls.geojson";
const char *OUTPUT_PATH_WITH_HULLS = "./output_data/1a_parks_with_concave_hulls.geojson";

// Whitelist of eapply values to process
// Empty set means process all features
std::set<std::string> EAPPLY_WHITELIST = {
    // "Van Voorhees Playground",
    // "Grand Army Plaza",
    // "Prospect Park",
    // "Red Hook Recreation Area",
    // "Broadway Malls 59th-110th"
    // Add more park names here as needed
};

const float METERS_PER_DEGREE = 111319.9;
const float CONCAVE_HULL_LENGTH_THRESHOLD_METERS = 50.0;
const float CONCAVE_HULL_LENGTH_THRESHOLD = CONCAVE_HULL_LENGTH_THRESHOLD_METERS / METERS_PER_DEGREE;
const float CONCAVE_HULL_LENGTH_INCREMENT_METERS = 20.0;
const float CONCAVE_HULL_LENGTH_INCREMENT = CONCAVE_HULL_LENGTH_INCREMENT_METERS / METERS_PER_DEGREE;
const int MAX_ATTEMPTS = 100; // Maximum number of threshold increments to try

// Threshold for tiny polygon removal (in square meters)
const double TINY_POLYGON_AREA_THRESHOLD_SQ_METERS = 500.0; // 100 square meters
const double SQ_METERS_PER_SQ_DEGREE = METERS_PER_DEGREE * METERS_PER_DEGREE;
const double TINY_POLYGON_AREA_THRESHOLD = TINY_POLYGON_AREA_THRESHOLD_SQ_METERS / SQ_METERS_PER_SQ_DEGREE;

std::string readFile(const char *filename)
{
  std::ifstream file(filename);
  if (!file.is_open())
  {
    throw std::runtime_error(std::string("Could not open file: ") + filename);
  }
  std::stringstream buffer;
  buffer << file.rdbuf();
  return buffer.str();
}

void writeFile(const char *filename, const std::string &content)
{
  std::ofstream file(filename);
  if (!file.is_open())
  {
    throw std::runtime_error(std::string("Could not write to file: ") + filename);
  }
  file << content;
}

bool createDirectoryIfNotExists(const std::string &dir_path)
{
#if __cplusplus >= 201703L
  namespace fs = std::filesystem;
  if (!fs::exists(dir_path))
  {
    return fs::create_directory(dir_path);
  }
  return true;
#else
  struct stat st = {0};
  if (stat(dir_path.c_str(), &st) == -1)
  {
    return mkdir(dir_path.c_str(), 0700) == 0;
  }
  return true;
#endif
}

int main()
{
  try
  {
    /* New factory with default (float) precision model */
    GeometryFactory::Ptr factory = GeometryFactory::create();

    /* Read GeoJSON file */
    std::cout << "Reading GeoJSON file: " << SOURCE_DATA_FILE << std::endl;
    std::string geojson_content = readFile(SOURCE_DATA_FILE);

    /* Create GeoJSON reader */
    GeoJSONReader reader(*factory);

    /* Parse the GeoJSON */
    GeoJSONFeatureCollection feature_collection = reader.readFeatures(geojson_content);
    const std::vector<GeoJSONFeature> &features = feature_collection.getFeatures();

    std::cout << "Processing " << features.size() << " features..." << std::endl;

    /* Process each feature */
    std::vector<GeoJSONFeature> output_features;            // For concave hulls only
    std::vector<GeoJSONFeature> output_features_with_hulls; // For original + concave hull property
    int processed = 0;
    int skipped = 0;

    for (const auto &feature : features)
    {
      const Geometry *geom = feature.getGeometry();
      const auto &properties = feature.getProperties();

      /* Check if this feature should be processed based on whitelist */
      bool should_process = EAPPLY_WHITELIST.empty(); // If whitelist is empty, process all

      if (!EAPPLY_WHITELIST.empty())
      {
        /* Check if feature has an "eapply" property and if it's in the whitelist */
        auto eapply_it = properties.find("eapply");
        if (eapply_it != properties.end() && eapply_it->second.isString())
        {
          std::string eapply_value = eapply_it->second.getString();
          should_process = EAPPLY_WHITELIST.count(eapply_value) > 0;
        }
      }

      if (!should_process)
      {
        /* Keep unprocessed features in both outputs as-is */
        std::unique_ptr<Geometry> geom_copy1(geom->clone());
        GeoJSONFeature feature_copy1(std::move(geom_copy1), properties, feature.getId());
        output_features.push_back(std::move(feature_copy1));

        std::unique_ptr<Geometry> geom_copy2(geom->clone());
        GeoJSONFeature feature_copy2(std::move(geom_copy2), properties, feature.getId());
        output_features_with_hulls.push_back(std::move(feature_copy2));

        skipped++;
        continue;
      }

      if (geom && geom->getGeometryTypeId() == GEOS_MULTIPOLYGON)
      {
        /* Compute concave hull with adaptive threshold */
        std::unique_ptr<Geometry> hull;
        float current_threshold = CONCAVE_HULL_LENGTH_THRESHOLD;
        int attempts = 0;

        try
        {
          std::cout << "Name: " << properties.find("name311")->second.getString() << std::endl;
        }
        catch (const std::exception &e)
        {
          std::cout << "Error: " << e.what() << std::endl;
        }
        for (attempts = 0; attempts < MAX_ATTEMPTS; attempts++)
        {
          try
          {
            std::cout << "Current threshold: " << current_threshold * METERS_PER_DEGREE << " meters" << std::endl;
            hull = ConcaveHullOfPolygons::concaveHullByLength(
                geom,
                current_threshold,
                true,   /* isTight - keep boundary tight to input polygons */
                false); /* isHolesAllowed - don't allow holes in the hull */
          }
          catch (const std::exception &e)
          {
            std::cout << "Error: " << e.what() << std::endl;
            std::cout << "Concave Hull Failed, increasing threshold" << std::endl;
            current_threshold += CONCAVE_HULL_LENGTH_INCREMENT;
            continue;
          }

          /* Check if result is a single polygon */
          if (hull && hull->getGeometryTypeId() == GEOS_MULTIPOLYGON)
          {
            const MultiPolygon *mp = dynamic_cast<const MultiPolygon *>(hull.get());
            if (mp && mp->getNumGeometries() == 1)
            {
              /* Success! Single polygon achieved */
              break;
            }
          }
          else if (hull && hull->getGeometryTypeId() == GEOS_POLYGON)
          {
            /* Result is a single Polygon (not even MultiPolygon), perfect! */
            break;
          }

          /* Still multiple polygons, increase threshold and retry */
          current_threshold += CONCAVE_HULL_LENGTH_INCREMENT;
        }

        /* Log if multiple attempts were needed */
        if (attempts > 0)
        {
          const auto &props = feature.getProperties();
          auto eapply_it = props.find("eapply");
          std::string park_name = "(unknown)";
          if (eapply_it != props.end() && eapply_it->second.isString())
          {
            park_name = eapply_it->second.getString();
          }

          float final_threshold_meters = current_threshold * METERS_PER_DEGREE;
          std::cout << "  ⚡ " << park_name << " required " << (attempts + 1)
                    << " attempts (threshold: " << (int)final_threshold_meters << "m)" << std::endl;
        }

        /* Create feature with hull geometry for first output */
        std::unique_ptr<Geometry> hull_copy(hull->clone());
        GeoJSONFeature hull_feature(std::move(hull), feature.getProperties(), feature.getId());
        output_features.push_back(std::move(hull_feature));

        /* Create feature with original geometry + concave_hull_polygon property for second output */
        std::unique_ptr<Geometry> original_geom_copy(geom->clone());
        auto properties_with_hull = feature.getProperties();

        /* Serialize concave hull to GeoJSON and add as property */
        GeoJSONWriter geom_writer;
        std::string hull_geojson = geom_writer.write(hull_copy.get());
        properties_with_hull["concave_hull_polygon"] = GeoJSONValue(hull_geojson);

        GeoJSONFeature feature_with_hull(std::move(original_geom_copy), properties_with_hull, feature.getId());
        output_features_with_hulls.push_back(std::move(feature_with_hull));

        processed++;
        if (processed % 100 == 0)
        {
          std::cout << "  Processed " << processed << " features..." << std::endl;
        }
      }
      else
      {
        /* Keep the feature as-is if it's not a MultiPolygon */
        /* Need to make a copy since the original is const */
        std::unique_ptr<Geometry> geom_copy(geom->clone());
        GeoJSONFeature new_feature(std::move(geom_copy), feature.getProperties(), feature.getId());
        output_features.push_back(std::move(new_feature));

        /* Also add to second output (no concave hull property for non-MultiPolygon) */
        std::unique_ptr<Geometry> geom_copy2(geom->clone());
        GeoJSONFeature new_feature2(std::move(geom_copy2), feature.getProperties(), feature.getId());
        output_features_with_hulls.push_back(std::move(new_feature2));

        processed++;
      }
    }

    std::cout << "Processed " << processed << " features" << std::endl;
    if (skipped > 0)
    {
      std::cout << "Skipped " << skipped << " features (not in whitelist)" << std::endl;
    }

    /* Check for MultiPolygons with more than one polygon */
    std::vector<std::string> multi_polygon_names;
    std::vector<GeoJSONFeature> multi_polygon_features;
    int tiny_polygons_removed = 0;

    for (size_t i = 0; i < output_features.size(); ++i)
    {
      auto &feature = output_features[i];
      const Geometry *geom = feature.getGeometry();
      if (geom && geom->getGeometryTypeId() == GEOS_MULTIPOLYGON)
      {
        const MultiPolygon *mp = dynamic_cast<const MultiPolygon *>(geom);
        if (mp && mp->getNumGeometries() > 1)
        {
          /* Find the eapply value for this feature */
          const auto &properties = feature.getProperties();
          auto eapply_it = properties.find("eapply");
          std::string eapply_name;
          if (eapply_it != properties.end() && eapply_it->second.isString())
          {
            eapply_name = eapply_it->second.getString();
          }
          else
          {
            eapply_name = "(no eapply value)";
          }

          /* Edge case: if exactly 2 polygons and one is tiny, remove the tiny one */
          bool handled = false;
          if (mp->getNumGeometries() == 2)
          {
            const Geometry *poly1 = mp->getGeometryN(0);
            const Geometry *poly2 = mp->getGeometryN(1);
            double area1 = poly1->getArea();
            double area2 = poly2->getArea();

            const Geometry *larger_poly = nullptr;
            double smaller_area = 0.0;

            if (area1 < area2 && area1 < TINY_POLYGON_AREA_THRESHOLD)
            {
              larger_poly = poly2;
              smaller_area = area1;
              handled = true;
            }
            else if (area2 < area1 && area2 < TINY_POLYGON_AREA_THRESHOLD)
            {
              larger_poly = poly1;
              smaller_area = area2;
              handled = true;
            }

            if (handled && larger_poly)
            {
              /* Remove the tiny polygon by keeping only the larger one */
              std::unique_ptr<Geometry> larger_copy(larger_poly->clone());
              GeoJSONFeature new_feature(std::move(larger_copy), properties, feature.getId());
              output_features[i] = std::move(new_feature);

              double smaller_area_sqm = smaller_area * SQ_METERS_PER_SQ_DEGREE;
              std::cout << "  ✓ " << eapply_name << ": Removed tiny polygon ("
                        << (int)smaller_area_sqm << " sq m)" << std::endl;
              tiny_polygons_removed++;
            }
          }

          /* If not handled by edge case, add to problematic list */
          if (!handled)
          {
            multi_polygon_names.push_back(eapply_name);

            /* Copy the feature for the separate file */
            std::unique_ptr<Geometry> geom_copy(geom->clone());
            GeoJSONFeature feature_copy(std::move(geom_copy), properties, feature.getId());
            multi_polygon_features.push_back(std::move(feature_copy));
          }
        }
      }
    }

    if (tiny_polygons_removed > 0)
    {
      std::cout << "\n✓ Removed " << tiny_polygons_removed
                << " tiny polygon(s) from MultiPolygons." << std::endl;
    }

    if (!multi_polygon_names.empty())
    {
      std::cout << "\n⚠️  WARNING: " << multi_polygon_names.size()
                << " feature(s) still have MultiPolygons with multiple polygons:" << std::endl;
      for (const auto &name : multi_polygon_names)
      {
        std::cout << "  - " << name << std::endl;
      }
      std::cout << "\nConsider increasing CONCAVE_HULL_LENGTH_THRESHOLD to merge these polygons." << std::endl;

      /* Write each multi-polygon issue as a separate GeoJSON file in 'issue_geojson/' */
      const std::string issue_dir = "temp/issue_geojson";
      if (!createDirectoryIfNotExists(issue_dir))
      {
        std::cerr << "Warning: Failed to create directory '" << issue_dir << "'" << std::endl;
      }
      else
      {
        GeoJSONWriter single_issue_writer;
        for (size_t i = 0; i < multi_polygon_features.size(); ++i)
        {
          const GeoJSONFeature &issue_feature = multi_polygon_features[i];
          GeoJSONFeatureCollection single_feature_collection({issue_feature});
          std::string single_geojson = single_issue_writer.write(single_feature_collection);
          std::string filename = issue_dir + "/issue_" + std::to_string(i + 1) + ".geojson";
          writeFile(filename.c_str(), single_geojson);
          std::cout << "  - Written to: " << filename << std::endl;
        }
      }
    }
    else if (processed > 0)
    {
      std::cout << "\n✓ All processed features have single-polygon geometries." << std::endl;
    }

    /* Write output GeoJSON files */
    GeoJSONWriter writer;

    /* Write concave hulls only */
    GeoJSONFeatureCollection output_collection_hulls(std::move(output_features));
    std::string output_geojson_hulls = writer.write(output_collection_hulls);
    writeFile(OUTPUT_PATH_HULLS, output_geojson_hulls);
    std::cout << "Concave hulls written to: " << OUTPUT_PATH_HULLS << std::endl;

    /* Write original geometries with concave hull properties */
    GeoJSONFeatureCollection output_collection_with_hulls(std::move(output_features_with_hulls));
    std::string output_geojson_with_hulls = writer.write(output_collection_with_hulls);
    writeFile(OUTPUT_PATH_WITH_HULLS, output_geojson_with_hulls);
    std::cout << "Original geometries with concave hulls written to: " << OUTPUT_PATH_WITH_HULLS << std::endl;

    return 0;
  }
  catch (const std::exception &e)
  {
    std::cerr << "Error: " << e.what() << std::endl;
    return 1;
  }
}
import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Container,
  Row,
  Col,
  Table,
  Spinner,
  Alert,
  Button,
  Badge
} from 'react-bootstrap';
import Layout from '../components/Layout';

export default function EpisodeDetail() {
  const { key } = useParams();
  const [episode, setEpisode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`/api/episode/${encodeURIComponent(key)}`)
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setEpisode(data))
      .catch(err => setError(err))
      .finally(() => setLoading(false));
  }, [key]);

  if (loading) {
    return (
      <Layout>
        <Container className="py-4 text-center">
          <Spinner animation="border" role="status" />
        </Container>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout>
        <Container className="py-4">
          <Alert variant="danger">Error loading episode: {error.toString()}</Alert>
          <Button as={Link} to="/" variant="outline-light" className="mt-2">
            ← Back to Library
          </Button>
        </Container>
      </Layout>
    );
  }

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">
          ← Back to Library
        </Button>
        <Row className="mb-4">
          <Col>
            <h1>Episode Details</h1>
          </Col>
        </Row>
        <Table striped bordered hover responsive variant="dark">
          <tbody>
            <tr>
              <th>Expected Title</th>
              <td>{episode.expectedTitle}</td>
            </tr>
            <tr>
              <th>Normalized Expected</th>
              <td>{episode.norm_expected}</td>
            </tr>
            <tr>
              <th>Actual Title</th>
              <td>{episode.actualTitle}</td>
            </tr>
            <tr>
              <th>Normalized Actual</th>
              <td>{episode.norm_extracted}</td>
            </tr>
            <tr>
              <th>Confidence</th>
              <td>{episode.confidence}</td>
            </tr>
            <tr>
              <th>Tags</th>
              <td>
                {episode.tags?.map(tag => (
                  <Badge key={tag} bg="secondary" className="me-1">
                    {tag}
                  </Badge>
                ))}
              </td>
            </tr>
            <tr>
              <th>Substring Override?</th>
              <td>{episode.substring_override ? 'Yes' : 'No'}</td>
            </tr>
            <tr>
              <th>Missing Title?</th>
              <td>{episode.missing_title ? 'Yes' : 'No'}</td>
            </tr>
          </tbody>
        </Table>
      </Container>
    </Layout>
  );
}
